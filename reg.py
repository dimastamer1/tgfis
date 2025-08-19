import os
import asyncio
import random
from datetime import datetime
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    PhoneNumberInvalidError,
    PhoneNumberBannedError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    FloodWaitError
)
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
load_dotenv('proxy.env')  # Отдельный файл для прокси

# Configuration
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
MONGO_URI = os.getenv("MONGO_URI")

# Proxy configuration
PROXIES = [
    {
        'type': 'socks5',
        'host': os.getenv("PROXY_HOST"),
        'port': int(os.getenv("PROXY_PORT")),
        'username': os.getenv("PROXY_USER"),
        'password': os.getenv("PROXY_PASS")
    },
    {
        'type': 'socks5',
        'host': os.getenv("PROXY1_HOST"),
        'port': int(os.getenv("PROXY1_PORT")),
        'username': os.getenv("PROXY1_USER"),
        'password': os.getenv("PROXY1_PASS")
    }
]

# Database setup
mongo = MongoClient(MONGO_URI)
db = mongo["telegram_accounts"]
sessions_col = db["registered_sessions"]

class AccountRegistrar:
    def __init__(self):
        self.client = None
        self.current_proxy = None
    
    def get_random_proxy(self):
        """Get random proxy from list"""
        proxy = random.choice(PROXIES)
        return (
            proxy['type'],
            proxy['host'],
            proxy['port'],
            True,
            proxy['username'],
            proxy['password']
        )
    
    async def init_client(self):
        """Initialize client with random proxy"""
        max_retries = 3
        for _ in range(max_retries):
            try:
                self.current_proxy = self.get_random_proxy()
                self.client = TelegramClient(
                    StringSession(),
                    API_ID,
                    API_HASH,
                    proxy=self.current_proxy,
                    connection_retries=5
                )
                await self.client.connect()
                return True
            except Exception as e:
                print(f"[-] Ошибка подключения через прокси: {str(e)}")
                continue
        return False
    
    async def get_code(self, phone):
        """Try all possible methods to get verification code"""
        methods = [
            self._get_code_telegram,
            self._get_code_sms,
            self._get_code_call,
            self._get_code_flash_call
        ]
        
        for method in methods:
            if await method(phone):
                return True
        
        return False
    
    async def _get_code_telegram(self, phone):
        """Try to get code via Telegram app"""
        try:
            sent = await self.client.send_code_request(phone)
            print(f"\n[+] Код отправлен через {sent.type}")
            return True
        except Exception as e:
            print(f"[-] Telegram app: {str(e)}")
            return False
    
    async def _get_code_sms(self, phone):
        """Force SMS delivery"""
        try:
            await self.client.send_code_request(phone, force_sms=True)
            print("\n[+] Код отправлен через SMS")
            return True
        except Exception as e:
            print(f"[-] SMS: {str(e)}")
            return False
    
    async def _get_code_call(self, phone):
        """Try to get code via phone call"""
        try:
            await self.client.send_code_request(phone, allow_flashcall=True)
            print("\n[+] Ожидайте звонка с кодом")
            return True
        except Exception as e:
            print(f"[-] Звонок: {str(e)}")
            return False
    
    async def _get_code_flash_call(self, phone):
        """Try flash call method"""
        try:
            await self.client.send_code_request(phone, allow_flashcall=True)
            print("\n[+] Ожидайте флеш-звонка")
            return True
        except Exception as e:
            print(f"[-] Флеш-звонок: {str(e)}")
            return False
    
    async def register_account(self):
        print("\n=== УЛУЧШЕННАЯ СИСТЕМА РЕГИСТРАЦИИ ===")
        print("Автоматический подбор прокси и методов получения кода\n")
        
        # Get phone number
        while True:
            phone = input("Введите номер телефона (с кодом страны +): ").strip()
            if phone.startswith('+') and len(phone) > 5:
                break
            print("❌ Некорректный формат (пример: +593995555555 для Эквадора)")
        
        # Initialize client with proxy
        if not await self.init_client():
            print("\n❌ Не удалось подключиться через прокси")
            return
        
        try:
            # Try to send code
            if not await self.get_code(phone):
                print("\n❌ Не удалось отправить код. Попробуйте другой номер.")
                return
            
            # Code entry with multiple attempts
            for attempt in range(1, 4):
                code = input(f"\nВведите код подтверждения (попытка {attempt}/3): ").strip()
                
                try:
                    # Try to sign in
                    await self.client.sign_in(
                        phone=phone,
                        code=code,
                        first_name=input("Имя (необязательно): ").strip() or "User",
                        last_name=input("Фамилия (необязательно): ").strip() or ""
                    )
                    break
                except PhoneCodeInvalidError:
                    print("❌ Неверный код")
                    continue
                except PhoneCodeExpiredError:
                    print("❌ Код устарел. Запросите новый.")
                    if not await self.get_code(phone):
                        return
                    continue
                except FloodWaitError as e:
                    print(f"⏳ Ожидайте {e.seconds} секунд перед повторной попыткой")
                    await asyncio.sleep(e.seconds)
                    continue
                except Exception as e:
                    print(f"❌ Ошибка: {str(e)}")
                    return
            
            # Verify authorization
            if not await self.client.is_user_authorized():
                print("\n❌ Авторизация не удалась")
                return
            
            # Save session
            session_string = StringSession.save(self.client.session)
            
            # Get account info
            me = await self.client.get_me()
            country = "Unknown"
            try:
                from phonenumbers import geocoder, parse
                country = geocoder.description_for_number(parse(phone, None), "en")
            except:
                pass
            
            # Prepare account data
            account_data = {
                "phone": phone,
                "session": session_string,
                "first_name": me.first_name,
                "last_name": me.last_name or "",
                "username": me.username or "",
                "country": country,
                "proxy": self.current_proxy[1],
                "registered_at": datetime.now().isoformat(),
                "status": "active"
            }
            
            # Save to database
            sessions_col.insert_one(account_data)
            
            print("\n✅ АККАУНТ УСПЕШНО ЗАРЕГИСТРИРОВАН!")
            print(f"Номер: {phone}")
            print(f"Страна: {country}")
            print(f"Имя: {me.first_name}")
            print(f"Прокси: {self.current_proxy[1]}")
            print(f"Сессия: {session_string}")
            
        except PhoneNumberBannedError:
            print("\n❌ Этот номер заблокирован в Telegram")
        except PhoneNumberInvalidError:
            print("\n❌ Неверный формат номера")
        except Exception as e:
            print(f"\n❌ Критическая ошибка: {str(e)}")
        finally:
            if self.client:
                await self.client.disconnect()

if __name__ == '__main__':
    registrar = AccountRegistrar()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(registrar.register_account())