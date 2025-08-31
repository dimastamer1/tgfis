import requests
import random
import string
import time
import json
from urllib.parse import quote, urlencode

def generate_password():
    """Генерация безопасного пароля"""
    length = random.randint(10, 14)
    chars = string.ascii_letters + string.digits + "!@#$%"
    while True:
        pwd = ''.join(random.choice(chars) for _ in range(length))
        if (any(c.islower() for c in pwd) and
            any(c.isupper() for c in pwd) and
            any(c.isdigit() for c in pwd) and
            any(c in "!@#$%" for c in pwd)):
            return pwd

class TikTokSessionCreator:
    def __init__(self, proxy=None):
        self.session = requests.Session()
        self.proxy = proxy
        
        if proxy:
            self.session.proxies = {'http': proxy, 'https': proxy}
        
        # Устанавливаем стандартные заголовки браузера
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
        })
    
    def get_initial_cookies(self):
        """Получаем первоначальные куки со страницы регистрации"""
        print("🔍 Получаем initial cookies...")
        try:
            response = self.session.get('https://www.tiktok.com/signup/phone-or-email/email', timeout=30)
            
            # Проверяем какие куки установились
            cookies = self.session.cookies.get_dict()
            print(f"🍪 Initial cookies: {cookies}")
            
            return True
        except Exception as e:
            print(f"❌ Ошибка получения cookies: {e}")
            return False
    
    def get_csrf_token(self):
        """Извлекаем CSRF token из кук"""
        cookies = self.session.cookies.get_dict()
        return cookies.get('tt_csrf_token', '')
    
    def get_verify_fp(self):
        """Пытаемся получить verifyFp"""
        # Генерируем verifyFp по формату TikTok
        return f"verify_{''.join(random.choices(string.ascii_lowercase + string.digits, k=10))}_{''.join(random.choices(string.digits, k=13))}"
    
    def send_verification_code_v1(self, email):
        """Первый метод отправки кода"""
        url = "https://www.tiktok.com/passport/email/send_verify_code/"
        
        csrf_token = self.get_csrf_token()
        verify_fp = self.get_verify_fp()
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-Secsdk-Csrf-Token': csrf_token,
            'Referer': 'https://www.tiktok.com/signup/phone-or-email/email',
            'Origin': 'https://www.tiktok.com',
        }
        
        data = {
            'email': email,
            'type': '1',
            'verifyFp': verify_fp,
            'device_platform': 'web_pc',
            'aid': '1988',
        }
        
        print(f"📧 Метод 1 - Отправка кода на {email}")
        print(f"🔑 VerifyFP: {verify_fp}")
        
        try:
            response = self.session.post(url, data=data, headers=headers, timeout=30)
            print(f"📨 Статус: {response.status_code}")
            print(f"📨 Ответ: {response.text}")
            
            if response.status_code == 200:
                result = response.json()
                if result.get('status_code') == 0:
                    return True
            return False
                
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return False
    
    def send_verification_code_v2(self, email):
        """Второй метод отправки кода"""
        url = "https://www.tiktok.com/node/email/send_verification_code"
        
        headers = {
            'Content-Type': 'application/json',
            'Referer': 'https://www.tiktok.com/signup/phone-or-email/email',
            'Origin': 'https://www.tiktok.com',
        }
        
        data = {
            "email": email,
            "type": 1
        }
        
        print(f"📧 Метод 2 - Отправка кода на {email}")
        
        try:
            response = self.session.post(url, json=data, headers=headers, timeout=30)
            print(f"📨 Статус: {response.status_code}")
            print(f"📨 Ответ: {response.text}")
            
            if response.status_code == 200:
                result = response.json()
                if result.get('code') == 0:
                    return True
            return False
                
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return False
    
    def send_verification_code_v3(self, email):
        """Третий метод отправки кода (мобильный API)"""
        url = "https://api16-normal-c-useast1a.tiktokv.com/passport/email/send_verify_code/v2/"
        
        device_id = ''.join(random.choices(string.digits, k=19))
        
        params = {
            'email': email,
            'type': '1',
            'device_id': device_id,
            'iid': ''.join(random.choices(string.digits, k=19)),
            'os_version': '10',
            'version_code': '300904',
            'app_name': 'trill',
            'channel': 'googleplay',
            'device_platform': 'android',
            'device_type': 'SM-G975F',
            'locale': 'en_US',
            'resolution': '1440*3120',
            'sys_region': 'US',
            'carrier_region': 'US',
            'timezone_name': 'America/New_York',
            'account_region': 'US',
            'aid': '1233',
            'app_language': 'en',
            'current_region': 'US',
            'ac': 'wifi',
            'mcc_mnc': '310260',
            'os_api': '29',
            'ssmix': 'a',
            'manifest_version_code': '300904',
            'dpi': '480',
            'uuid': str(uuid.uuid4()),
            'openudid': hashlib.md5(str(time.time()).encode()).hexdigest(),
            'retry_type': 'no_retry',
            'ts': str(int(time.time())),
        }
        
        headers = {
            'User-Agent': 'com.zhiliaoapp.musically/300904 (Linux; U; Android 10; en_US; SM-G975F; Build/QP1A.190711.020; Cronet/TTNetVersion:5f7c5d77 2022-07-11 QuicVersion:47946d2a 2020-10-14)',
            'Accept': 'application/json',
        }
        
        print(f"📧 Метод 3 - Отправка кода на {email}")
        
        try:
            response = requests.post(url, data=params, headers=headers, timeout=30)
            print(f"📨 Статус: {response.status_code}")
            print(f"📨 Ответ: {response.text}")
            
            if response.status_code == 200:
                result = response.json()
                if result.get('message') == 'success':
                    return True
            return False
                
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return False

def main():
    print("🚀 TikTok Registration via Session")
    print("=" * 50)
    
    email = input("Введите email: ")
    password = generate_password()
    print(f"🔑 Пароль: {password}")
    
    # Инициализируем сессию
    creator = TikTokSessionCreator()
    
    # Получаем куки
    if not creator.get_initial_cookies():
        print("❌ Не удалось получить куки")
        return
    
    # Пробуем все методы по очереди
    methods = [
        creator.send_verification_code_v1,
        creator.send_verification_code_v2,
        creator.send_verification_code_v3
    ]
    
    for i, method in enumerate(methods, 1):
        print(f"\n🔧 Метод {i}:")
        if method(email):
            code = input("Введите код подтверждения: ")
            print(f"✅ Код получен: {code}")
            break
        else:
            print(f"❌ Метод {i} не сработал")
    
    print("\n🎯 Если ни один метод не сработал, используй браузерную автоматизацию")

if __name__ == "__main__":
    import uuid
    import hashlib
    main()