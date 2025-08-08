from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, AuthKeyUnregisteredError
import os

# ВСТАВЬ СЮДА ДАННЫЕ
API_ID = 28932534  # 👉 твой API_ID от my.telegram.org
API_HASH = "55a8ca92300de9d9c383db0b8db5a671"  # 👉 твой API_HASH
SESSION_STRING = "1AZWarzQBuyaX0COGcjyolSE3WTGFAAwQHVRkXzSA-lnRudZNLofjJQtr8FaFWTrGiiFipuwHeYWkJMv3-uueCkhW4rTJeoZUKH_0tJoG86_ioTduUevgiUVyxZ7-6cYgLKx7jn_7TCI3JjQ_-vgKy5HQTRDjMeaeTH8i7nsdoOWmIglVsgVHn3M4MieJDBnOF2oLAzpnAXCyqchI6OClLzDKfogo5A1-7EZSKceBdsyJBt0jZKqDMurPrNCSeCSNyHOwo4-pSNfKgWhe2dODo6WJvwYJ7i1NrnH8uOASdYBjwwtgZoTS8I8L8L8nZjSIg29FeN1g8ECATcmDLOOhRd7vcaGNq7Y="  # 👉 сессия

async def check_session():
    try:
        client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
        await client.connect()

        if not await client.is_user_authorized():
            print("❌ НЕВАЛИДНА (пользователь не авторизован)")
        else:
            me = await client.get_me()
            print(f"✅ ВАЛИДНА — @{me.username} / ID: {me.id}")
        await client.disconnect()

    except AuthKeyUnregisteredError:
        print("❌ НЕВАЛИДНА (AuthKeyUnregisteredError)")
    except SessionPasswordNeededError:
        print("✅ ВАЛИДНА (требуется 2FA пароль)")
    except Exception as e:
        print(f"❌ НЕВАЛИДНА (ошибка: {e})")

import asyncio
asyncio.run(check_session())
