from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, AuthKeyUnregisteredError
import os

# ВСТАВЬ СЮДА ДАННЫЕ
API_ID = 28932534  # 👉 твой API_ID от my.telegram.org
API_HASH = "55a8ca92300de9d9c383db0b8db5a671"  # 👉 твой API_HASH
SESSION_STRING = "1AZWarzwBu7lwvikSS1bZJ6ErnmyLJ1B6xUbOVnp-zrlEXePnWo5_0F-AF7rMzYq-_IjLsLsSe1a6GrSWydDbs3ZyWUBcnkmIVvaKd-bodgRk2iYFonAxhA5KfwspUf9Qcv4C28qrdDXzVq8E-Kb2XV16YyPtoapRkfBtj76PYjRwc0C3yLU2TZkg7RQSAhe1xpR1u8t_Eh6jPOyR2pi3z3QoVQIjkPAQzVd4SOdLDElMb_71DRZfD1zsr7sGl1wT-EmjsUMiJpkyVnon0h0bbKw5VfS0XPSRXe7j1mDZ1GSAVuRCn3GzzGD2nY_uuWbnRxbglft9_3sWyyVANqOitJpwLNBptFw="  # 👉 сессия

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
