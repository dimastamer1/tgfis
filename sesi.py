from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, AuthKeyUnregisteredError
import os

# ВСТАВЬ СЮДА ДАННЫЕ
API_ID = 28932534  # 👉 твой API_ID от my.telegram.org
API_HASH = "55a8ca92300de9d9c383db0b8db5a671"  # 👉 твой API_HASH
SESSION_STRING = "1AZWarzQBux5LLdZne0gd32NwHVlspE0hchqZa6kcEPc6tLx2kzaBnnK7Uy6IjbPMVdYXTlIbo1pi4WAFF7nPKgez9-9c_68vU0QuLYAXZeKeJ0JeW3cvgqn7Hh_4Kfhlfo1YKxyfouFEb4NuauQfvj5MkJT-QtwAYYE23ib8-M4y-mji7UMHSba23n4NNK7DyXHGwZEnYe5bLj8uha-f7GtwkCUO_PdN-GpIYG0oYInVLCz3y2yKilNoAuIkqQ0xFOZSwN3GntsLgptVxDRo7bx0vQB9iDotM8bMTuVsvdZr2ZpuNHrjz4FiCfBQ5PQDuQFw-p93Q5TKkmz1OIS38vu-z9Neta8="  # 👉 сессия

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
