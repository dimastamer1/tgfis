import requests
import random
import time
import re
from colorama import Fore, Style, init
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from webdriver_manager.chrome import ChromeDriverManager

# Инициализируем colorama
init(autoreset=True)

# ========== КОНФИГУРАЦИЯ ==========
FIRSTMAIL_API_KEY = "7fab9999-cd63-4d7d-98e0-d717098792d7"  # Замени на свой ключ
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
PROXY = None
NEW_PASSWORD = "Qwer123@@"  # Новый пароль для всех аккаунтов
MAX_RETRIES = 3  # Максимальное количество повторных попыток при ошибке "слишком много попыток"
RETRY_DELAY = 30  # Задержка между попытками (в секундах)

class TikTokAutoLogin:
    def __init__(self, email, password, username, tikTokPassword):
        self.email = email
        self.password = password
        self.username = username
        self.tikTokPassword = tikTokPassword
        self.driver = None
        self.is_logged_in = False

    def log(self, message, color=Fore.WHITE):
        print(f"{color}[{self.username}] {message}{Style.RESET_ALL}")

    def setup_driver(self):
        """Настройка Selenium WebDriver с американскими настройками и поддержкой прокси"""
        options = Options()
        options.headless = False  # Видимый браузер для отладки
        options.add_argument(f"user-agent={USER_AGENT}")
        options.add_argument("--disable-webrtc")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--lang=en-US")  # Американский английский
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")  # Антидетект автоматизации
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)

        # Настройка часового пояса и геолокации (США)
        options.add_argument("--timezone=America/New_York")
        options.add_experimental_option("prefs", {
            "intl.accept_languages": "en-US,en",
            "profile.default_content_setting_values.geolocation": 1
        })

        # Поддержка прокси
        if PROXY:
            self.log("Используем прокси...", Fore.YELLOW)
            options.add_argument(f'--proxy-server={PROXY["http"]}')

        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        # Скрываем признаки автоматизации
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """
        })

    def get_firstmail_code(self):
        """Получаем код из Firstmail"""
        self.log("Получаем код из Firstmail...", Fore.YELLOW)
        try:
            time.sleep(12)  # Ждем письма
            inbox_url = f"https://api.firstmail.org/mailbox/{self.email}"
            headers = {
                "Authorization": f"Bearer {FIRSTMAIL_API_KEY}",
                "User-Agent": USER_AGENT
            }
            response = requests.get(inbox_url, headers=headers, timeout=30, proxies=PROXY)
            response.raise_for_status()
            messages = response.json().get('messages', [])
            for msg in messages:
                if 'TikTok' in msg.get('from', '') or 'tiktok' in msg.get('from', '').lower():
                    message_id = msg['id']
                    msg_url = f"https://api.firstmail.org/message/{message_id}"
                    msg_response = requests.get(msg_url, headers=headers, timeout=30, proxies=PROXY)
                    msg_response.raise_for_status()
                    msg_body = msg_response.json().get('body', '')
                    code_match = re.search(r'(\d{4,6})', msg_body)
                    if code_match:
                        code = code_match.group(1)
                        self.log(f"Код найден: {code}", Fore.GREEN)
                        return code
            self.log("Код не найден в письмах", Fore.RED)
            return None
        except Exception as e:
            self.log(f"Ошибка Firstmail: {e}", Fore.RED)
            return None

    def reset_password(self):
        """Процесс восстановления пароля с повторными попытками"""
        self.log("Начинаем восстановление пароля...", Fore.CYAN)
        for attempt in range(MAX_RETRIES):
            try:
                wait = WebDriverWait(self.driver, 30)

                # Клик на "Забыли пароль?"
                forgot_link = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, '//a[contains(text(), "Forgot password?") or contains(text(), "Забыли пароль?") or contains(@class, "forgot-password")]')
                ))
                self.log("Ссылка 'Забыли пароль?' найдена", Fore.GREEN)
                ActionChains(self.driver).move_to_element(forgot_link).pause(random.uniform(0.5, 1)).click().perform()

                # Ввод email
                email_field = wait.until(EC.presence_of_element_located(
                    (By.XPATH, '//input[@type="text" or @type="email" or contains(@placeholder, "email") or contains(@placeholder, "почты") or contains(@class, "input")]')
                ))
                self.log("Поле для email найдено", Fore.GREEN)
                ActionChains(self.driver).move_to_element(email_field).click().perform()
                time.sleep(random.uniform(0.5, 1.5))
                for char in self.email:
                    email_field.send_keys(char)
                    time.sleep(random.uniform(0.1, 0.3))

                # Кнопка "Отправить код"
                send_code_button = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, '//button[contains(text(), "Send code") or contains(text(), "Отправить код") or contains(text(), "Отправить") or contains(@class, "send-code")]')
                ))
                self.log("Кнопка 'Отправить код' найдена", Fore.GREEN)
                ActionChains(self.driver).move_to_element(send_code_button).pause(random.uniform(0.5, 1)).click().perform()

                # Проверяем наличие ошибки "слишком много попыток"
                try:
                    error_message = wait.until(EC.presence_of_element_located(
                        (By.XPATH, '//div[contains(text(), "Too many attempts") or contains(text(), "Слишком много попыток")]')
                    ))
                    self.log(f"Ошибка: Слишком много попыток. Попытка {attempt + 1}/{MAX_RETRIES}", Fore.RED)
                    if attempt < MAX_RETRIES - 1:
                        self.log(f"Ждем {RETRY_DELAY} секунд перед повторной попыткой...", Fore.YELLOW)
                        time.sleep(RETRY_DELAY)
                        self.driver.refresh()
                        continue
                    else:
                        self.log("Достигнуто максимальное количество попыток", Fore.RED)
                        return False
                except:
                    self.log("Ошибки 'Слишком много попыток' не обнаружено, продолжаем...", Fore.YELLOW)

                # Получаем и вводим код
                code = self.get_firstmail_code()
                if not code:
                    return False

                code_field = wait.until(EC.presence_of_element_located(
                    (By.XPATH, '//input[contains(@placeholder, "code") or contains(@placeholder, "код") or contains(@class, "code-input")]')
                ))
                self.log("Поле для кода найдено", Fore.GREEN)
                ActionChains(self.driver).move_to_element(code_field).click().perform()
                for char in code:
                    code_field.send_keys(char)
                    time.sleep(random.uniform(0.1, 0.3))

                # Поля для нового пароля и подтверждения
                new_pass_field = wait.until(EC.presence_of_element_located(
                    (By.XPATH, '//input[@type="password" and (contains(@placeholder, "New password") or contains(@placeholder, "Новый пароль") or position()=1)]')
                ))
                confirm_pass_field = self.driver.find_element(
                    By.XPATH, '//input[@type="password" and (contains(@placeholder, "Confirm password") or contains(@placeholder, "Подтвердите пароль") or position()=2)]'
                )
                self.log("Поля для нового пароля найдены", Fore.GREEN)

                # Ввод нового пароля
                ActionChains(self.driver).move_to_element(new_pass_field).click().perform()
                for char in NEW_PASSWORD:
                    new_pass_field.send_keys(char)
                    time.sleep(random.uniform(0.1, 0.3))
                ActionChains(self.driver).move_to_element(confirm_pass_field).click().perform()
                for char in NEW_PASSWORD:
                    confirm_pass_field.send_keys(char)
                    time.sleep(random.uniform(0.1, 0.3))

                # Кнопка подтверждения сброса
                confirm_button = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, '//button[contains(text(), "Confirm") or contains(text(), "Подтвердить") or contains(text(), "Reset") or contains(text(), "Сбросить") or contains(@class, "submit")]')
                ))
                self.log("Кнопка подтверждения найдена", Fore.GREEN)
                ActionChains(self.driver).move_to_element(confirm_button).pause(random.uniform(0.5, 1)).click().perform()

                self.log("Пароль успешно сброшен!", Fore.GREEN)
                return True
            except Exception as e:
                self.log(f"Ошибка восстановления пароля: {e}", Fore.RED)
                self.driver.save_screenshot(f"error_reset_{self.username}_attempt_{attempt}.png")
                with open(f"page_source_reset_{self.username}_attempt_{attempt}.html", "w", encoding="utf-8") as f:
                    f.write(self.driver.page_source)
                if attempt < MAX_RETRIES - 1:
                    self.log(f"Ждем {RETRY_DELAY} секунд перед повторной попыткой...", Fore.YELLOW)
                    time.sleep(RETRY_DELAY)
                    self.driver.refresh()
                continue
        return False

    def login(self):
        """Основной метод: Восстановление пароля и логин"""
        self.setup_driver()
        try:
            self.driver.get('https://www.tiktok.com/login/phone-or-email/email?lang=en')

            # Проверяем наличие CAPTCHA
            try:
                wait = WebDriverWait(self.driver, 30)
                captcha = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div.captcha_verify_container')))
                self.log("Обнаружена CAPTCHA! Пожалуйста, решите её вручную.", Fore.RED)
                input("Нажмите Enter после решения CAPTCHA...")
            except:
                self.log("CAPTCHA не обнаружена, продолжаем...", Fore.YELLOW)

            # Выполняем восстановление пароля
            if not self.reset_password():
                return False

            # После сброса входим с новым паролем
            self.driver.get('https://www.tiktok.com/login/phone-or-email/email?lang=en')
            wait = WebDriverWait(self.driver, 30)

            # Поле email/username
            email_field = wait.until(EC.presence_of_element_located(
                (By.XPATH, '//input[@type="text" or @type="email" or contains(@placeholder, "email") or contains(@placeholder, "username") or contains(@class, "input")]')
            ))
            ActionChains(self.driver).move_to_element(email_field).click().perform()
            for char in self.username or self.email:
                email_field.send_keys(char)
                time.sleep(random.uniform(0.1, 0.3))

            # Поле пароля
            password_field = wait.until(EC.presence_of_element_located(
                (By.XPATH, '//input[@type="password"]')
            ))
            ActionChains(self.driver).move_to_element(password_field).click().perform()
            for char in NEW_PASSWORD:
                password_field.send_keys(char)
                time.sleep(random.uniform(0.1, 0.3))

            # Кнопка "Войти"
            login_button = wait.until(EC.element_to_be_clickable(
                (By.XPATH, '//button[contains(text(), "Log in") or contains(text(), "Войти") or contains(@class, "login-button")]')
            ))
            ActionChains(self.driver).move_to_element(login_button).pause(random.uniform(0.5, 1)).click().perform()

            # Проверяем успешность логина
            time.sleep(5)
            if 'login' not in self.driver.current_url and ('foryou' in self.driver.current_url or 'profile' in self.driver.current_url):
                self.is_logged_in = True
                self.log("Успешный вход с новым паролем!", Fore.GREEN)
                return True
            else:
                self.log(f"Ошибка входа после сброса, текущий URL: {self.driver.current_url}", Fore.RED)
                self.driver.save_screenshot(f"error_{self.username}.png")
                with open(f"page_source_{self.username}.html", "w", encoding="utf-8") as f:
                    f.write(self.driver.page_source)
                return False
        except Exception as e:
            self.log(f"Ошибка логина: {e}", Fore.RED)
            self.driver.save_screenshot(f"error_{self.username}.png")
            with open(f"page_source_{self.username}.html", "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            return False
        finally:
            if not self.is_logged_in:
                self.driver.quit()

    def warmup_session(self):
        """Прогрев аккаунта"""
        if not self.is_logged_in:
            return
        self.log("Начинаем прогрев...", Fore.MAGENTA)
        try:
            self.driver.get('https://www.tiktok.com/foryou?lang=en')
            time.sleep(5)
            actions = ['scroll', 'watch', 'like', 'follow']
            for i in range(15):
                action = random.choice(actions)
                self.log(f"Действие {i+1}: {action}", Fore.LIGHTBLUE_EX)
                if action == 'scroll':
                    self.driver.execute_script("window.scrollBy(0, " + str(random.randint(500, 1500)) + ");")
                    time.sleep(random.uniform(2, 5))
                elif action == 'watch':
                    time.sleep(random.randint(10, 20))
                elif action == 'like':
                    try:
                        like_button = self.driver.find_element(By.XPATH, '//button[contains(@aria-label, "like") or contains(@class, "like")]')
                        ActionChains(self.driver).move_to_element(like_button).pause(random.uniform(0.5, 1)).click().perform()
                    except:
                        self.log("Кнопка лайка не найдена", Fore.YELLOW)
                    time.sleep(2)
                elif action == 'follow':
                    try:
                        follow_button = self.driver.find_element(By.XPATH, '//button[contains(text(), "Follow") or contains(text(), "Подписаться") or contains(@class, "follow")]')
                        ActionChains(self.driver).move_to_element(follow_button).pause(random.uniform(0.5, 1)).click().perform()
                    except:
                        self.log("Кнопка подписки не найдена", Fore.YELLOW)
                    time.sleep(3)
        except Exception as e:
            self.log(f"Ошибка прогрева: {e}", Fore.RED)
        finally:
            self.log("Прогрев завершен!", Fore.GREEN)
            self.driver.quit()

def main():
    print(Fore.CYAN + "=== TikTok Auto Login & Warmup ===")
    print("Введите данные аккаунтов в формате: email:pass:username:password")
    print("Введите 'START' чтобы начать")
    accounts = []
    while True:
        line = input().strip()
        if line.upper() == 'START':
            break
        if line and len(line.split(':')) == 4:
            accounts.append(line.split(':'))
        elif line:
            print(Fore.RED + "Неверный формат! Используйте: email:pass:username:password")
    if not accounts:
        print(Fore.RED + "Нет аккаунтов для обработки")
        return
    print(Fore.YELLOW + f"Начинаем обработку {len(accounts)} аккаунтов...")
    for acc_data in accounts:
        email, mail_pass, username, tikTok_pass = acc_data
        login = TikTokAutoLogin(email, mail_pass, username, tikTok_pass)
        if login.login():
            login.warmup_session()
        else:
            print(Fore.RED + f"Не удалось войти в {username}")

if __name__ == "__main__":
    main()