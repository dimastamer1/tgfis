import requests
import re
import time
from colorama import Fore, Style, init
import urllib.parse

# Инициализируем colorama
init(autoreset=True)

# Конфигурация
FIRSTMAIL_API_KEY = "40512629-2f17-4aa9-8cc9-cf12d0fc53c0"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"

def log(message, color=Fore.WHITE):
    print(f"{color}{message}{Style.RESET_ALL}")

def get_firstmail_code(email, mail_pass, max_attempts=8, delay=10):
    """Получаем код из Firstmail с правильным API endpoint"""
    log(f"Получаем код из Firstmail для {email} (максимум {max_attempts} попыток)...", Fore.YELLOW)
    
    try:
        # Кодируем email и password для URL
        encoded_email = urllib.parse.quote(email)
        encoded_password = urllib.parse.quote(mail_pass)
        
        url = f"https://api.firstmail.ltd/v1/market/get/message?username={encoded_email}&password={encoded_password}"
        headers = {
            "accept": "application/json",
            "X-API-KEY": FIRSTMAIL_API_KEY,
            "User-Agent": USER_AGENT
        }
        
        for attempt in range(max_attempts):
            try:
                response = requests.get(url, headers=headers, timeout=35)
                
                if response.status_code == 200:
                    messages = response.json()
                    log(f"Ответ API: {messages}", Fore.YELLOW)
                    
                    # Если ответ - словарь с has_message
                    if isinstance(messages, dict):
                        if not messages.get("has_message", False):
                            log(f"Попытка {attempt + 1}/{max_attempts}: нет сообщений, ждем {delay} секунд...", Fore.YELLOW)
                            time.sleep(delay)
                            continue
                        
                        msg = messages.get("message", {})
                        if ('TikTok' in msg.get('from', '') or 
                            'tiktok' in msg.get('from', '').lower() or
                            'TikTok' in msg.get('subject', '') or
                            'tiktok' in msg.get('subject', '').lower()):
                            
                            msg_body = msg.get('body', '') or msg.get('text', '') or msg.get('content', '')
                            log(f"Тело сообщения: {msg_body}", Fore.YELLOW)
                            
                            code_match = re.search(r'(\d{6})', msg_body)
                            if code_match:
                                code = code_match.group(1)
                                log(f"Код найден: {code}", Fore.GREEN)
                                return code
                    
                    # Если ответ - список сообщений
                    elif isinstance(messages, list):
                        messages.sort(key=lambda x: x.get('date', ''), reverse=True)
                        
                        for msg in messages:
                            if ('TikTok' in msg.get('from', '') or 
                                'tiktok' in msg.get('from', '').lower() or
                                'TikTok' in msg.get('subject', '') or
                                'tiktok' in msg.get('subject', '').lower()):
                                
                                msg_body = msg.get('body', '') or msg.get('text', '') or msg.get('content', '')
                                log(f"Тело сообщения: {msg_body}", Fore.YELLOW)
                                
                                code_match = re.search(r'(\d{6})', msg_body)
                                if code_match:
                                    code = code_match.group(1)
                                    log(f"Код найден: {code}", Fore.GREEN)
                                    return code
                    
                    log(f"Попытка {attempt + 1}/{max_attempts}: код не найден, ждем {delay} секунд...", Fore.YELLOW)
                    time.sleep(delay)
                
                else:
                    log(f"Ошибка API, статус: {response.status_code}, ответ: {response.text}", Fore.RED)
                    time.sleep(delay)
            
            except requests.exceptions.RequestException as e:
                log(f"Ошибка запроса к Firstmail (попытка {attempt + 1}): {e}", Fore.RED)
                time.sleep(delay)
            
            except Exception as e:
                log(f"Неожиданная ошибка (попытка {attempt + 1}): {e}", Fore.RED)
                time.sleep(delay)
        
        log("Код не найден в письмах после всех попыток", Fore.RED)
        return None
        
    except Exception as e:
        log(f"Критическая ошибка Firstmail: {e}", Fore.RED)
        return None

def main():
    print(Fore.CYAN + "=== TikTok Code Fetcher (Test Version) ===")
    print("Введите данные почт в формате: email:mail_password")
    print("Введите 'START' чтобы начать")
    
    accounts = []
    while True:
        line = input().strip()
        if line.upper() == 'START':
            break
        if line and len(line.split(':')) == 2:
            email, mail_pass = line.split(':')
            accounts.append((email, mail_pass))
        elif line:
            print(Fore.RED + "Неверный формат! Используйте: email:mail_password")
    
    if not accounts:
        print(Fore.RED + "Нет почт для обработки")
        return
    
    print(Fore.YELLOW + f"Начинаем проверку {len(accounts)} почт...")
    
    for i, (email, mail_pass) in enumerate(accounts):
        print(Fore.CYAN + f"\n=== Проверка {i + 1}/{len(accounts)} ===")
        log(f"Тестируем получение кода для {email}", Fore.CYAN)
        code = get_firstmail_code(email, mail_pass)
        if code:
            log(f"Успешно получен код: {code}", Fore.GREEN)
        else:
            log("Не удалось получить код", Fore.RED)
        
        # Пауза между почтами
        if i < len(accounts) - 1:
            pause_time = random.randint(5, 10)
            print(Fore.YELLOW + f"Ждем {pause_time} секунд перед следующей почтой...")
            time.sleep(pause_time)

if __name__ == "__main__":
    main()