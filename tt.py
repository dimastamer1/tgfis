import asyncio
import requests
import random
import time
import re
import string
import os
from colorama import Fore, Style, init
from playwright.async_api import async_playwright, Playwright, BrowserContext
import urllib.parse
import json
import logging
import sys

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Инициализация colorama для цветного вывода
init(autoreset=True)

# ========== КОНФИГУРАЦИЯ ==========
FIRSTMAIL_API_KEY = "40512629-2f17-4aa9-8cc9-cf12d0fc53c0"
MAX_RETRIES = 3
RETRY_DELAY = 60
CHECKBOX_COORDINATES = (784, 609)  # Настрой координаты под свое разрешение экрана

# Dolphin Anty конфигурация
PROFILE_ID = "653525242"  # Из твоего тестового кода
API_BASE_URL = "http://localhost:3001/v1.0/browser_profiles"
API_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiIxIiwianRpIjoiNGExY2RhNmYxYWE0MTQwMjY4NDJhZmI0ZGE1OTY1YzQzM2M2MmEzZmY0NDUzOWVjM2QzZjFkZjE3ZDI5Yzg1N2U5OTg1NmQ5MzI3MDhkOGMiLCJpYXQiOjE3NTYyMDE5NDUuNDQ1OTgxLCJuYmYiOjE3NTYyMDE5NDUuNDQ1OTg1LCJleHAiOjE3ODc3Mzc5NDUuNDM2NDQxLCJzdWIiOiIzMDE2NDI0Iiwic2NvcGVzIjpbXSwidGVhbV9pZCI6Mjk0NTA2MywidGVhbV9wbGFuIjoiZnJlZSIsInRlYW1fcGxhbl9leHBpcmF0aW9uIjoxNzA0ODc4MjY3fQ.q1cQsnqQh1_p1UO1Ix8ozOxlFsKzvLzIOKel3xTkKCghSx8jtIxZIz5H_quxto4YzLDMdWQuU6oUliNZhb3L59O8iBDMnAEvnaYky1PXGTuoLYiSzdrIsDMDIdNS8Q3jCRhhNXzJL-CAd0TaBTvrMopiCkoK6CnXgxJVM8NwqoA8Sf4zQ2Pl_ya7Zzy8xGzr0aKPi6i48F2CsM5N0sLpY0xNkWcN-HIK9Wi8M3bRQp74GK-XqtMbhHwKVFXofzLkmpXNs-_41TYFnPlGDxI1QuUiH49fITv3p9BdU9yk0WeiiYwqxxczdk7pPFqkxzUp6CrGzkst7bQu8o3Alqhwftq9dTryA1uJCu5-xWuqe-g9uA3V-vQwN3lZn_zDBI4i9YLxiqyH5yRerLRuclgrtHEoUmqofHNqZVNnY_XtHvOEowtT5RqygHcI-L736GLWe_WIuLwI2CeHUz41zLr0fVfKpBl2pQFSGSkIZJcjQJ9Mq5lLhVDz7dtuw5s4N46Ha-2aljzC9ApwTsAUhW6hR2ucj-zHe7SWy4i8urs-lNoBzGEC02ChIe7trrCdHtRyqW46JC6WX4rO2WXvqFkZW5gW5Ngk7VzUDrXe08bWhYGL6KmJ6LGd3NQ1BanAmGm2WLnOPtiZBDWfF5JP9Te0WW1XG1VMSS_uKc1Tn3ZhRCs"

async def start_dolphin_profile():
    """Запуск профиля Dolphin Anty через API"""
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    url = f"{API_BASE_URL}/{PROFILE_ID}/start?automation=1&headless=false"
    logger.info(f"Попытка запуска профиля: {url}")
    try:
        response = requests.get(url, headers=headers, timeout=15)
        logger.info(f"Статус ответа: {response.status_code}")
        logger.info(f"Текст ответа: {response.text}")
        if response.status_code == 200:
            try:
                data = response.json()
                logger.info(f"Данные ответа: {data}")
                return True
            except ValueError:
                logger.info("Ответ не содержит JSON, продолжаем...")
                return True
        else:
            logger.info(f"Ошибка запуска профиля: {response.text} (код: {response.status_code}), продолжаем...")
            return True
    except requests.exceptions.ConnectionError:
        logger.info("Не удалось подключиться к серверу, продолжаем...")
        return True
    except requests.exceptions.Timeout:
        logger.info("Таймаут запроса, продолжаем...")
        return True
    except requests.exceptions.RequestException as e:
        logger.info(f"Ошибка запроса: {e}, продолжаем...")
        return True

async def stop_dolphin_profile():
    """Остановка профиля Dolphin Anty через API"""
    url = f"{API_BASE_URL}/{PROFILE_ID}/stop"
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        logger.info(f"Статус ответа остановки: {response.status_code}")
        logger.info(f"Текст ответа остановки: {response.text}")
        if response.status_code == 200:
            logger.info("Профиль успешно остановлен")
    except Exception as e:
        logger.info(f"Ошибка при остановке профиля: {e}, продолжаем...")

class TikTokAutoRegister:
    def __init__(self, email: str, mail_pass: str):
        """Инициализация класса с email и паролем для почты"""
        self.email = email
        self.mail_pass = mail_pass
        self.username = self.generate_random_username()
        self.tikTokPassword = self.generate_strong_password()
        self.context: BrowserContext = None
        self.page = None
        self.is_registered = False

    def log(self, message: str, color=Fore.WHITE):
        """Логирование сообщений с цветом"""
        print(f"{color}[{self.email}] {message}{Style.RESET_ALL}")

    def generate_random_username(self) -> str:
        """Генерация случайного имени пользователя (10-12 символов, только буквы и цифры)"""
        chars = string.ascii_lowercase + string.digits
        length = random.randint(10, 12)
        return ''.join(random.choices(chars, k=length))

    def generate_strong_password(self) -> str:
        """Генерация сложного пароля с @, буквами и цифрами"""
        lowercase = ''.join(random.choices(string.ascii_lowercase, k=4))
        uppercase = ''.join(random.choices(string.ascii_uppercase, k=3))
        digits = ''.join(random.choices(string.digits, k=3))
        special = '@'
        password = list(lowercase + uppercase + digits + special)
        random.shuffle(password)
        return ''.join(password)

    async def setup_browser(self, playwright: Playwright):
        """Настройка браузера через Playwright"""
        try:
            # Пытаемся запустить профиль через API
            await start_dolphin_profile()
            # Используем локальный запуск, так как CDP не работает на бесплатном тарифе
            browser = await playwright.chromium.launch(headless=False)
            self.context = await browser.new_context()
            self.page = await self.context.new_page()
            self.log("Браузер настроен", Fore.GREEN)
            return True
        except Exception as e:
            self.log(f"Ошибка настройки браузера: {e}, пробуем локальный запуск", Fore.YELLOW)
            try:
                browser = await playwright.chromium.launch(headless=False)
                self.context = await browser.new_context()
                self.page = await self.context.new_page()
                self.log("Переключено на локальный запуск браузера", Fore.YELLOW)
                return True
            except Exception as e2:
                self.log(f"Критическая ошибка настройки браузера: {e2}", Fore.YELLOW)
                return False

    async def cleanup(self):
        """Очистка ресурсов после работы"""
        try:
            if self.page and not await self.page.is_closed():
                await self.page.close()
            if self.context:
                await self.context.close()
        except Exception as e:
            self.log(f"Ошибка очистки контекста браузера: {e}", Fore.YELLOW)
        finally:
            await stop_dolphin_profile()

    async def get_firstmail_code(self, max_attempts=12, delay=10) -> str | None:
        """Получение кода верификации от Firstmail"""
        self.log(f"Получение кода от Firstmail для {self.email} (макс. {max_attempts} попыток)...", Fore.YELLOW)
        try:
            encoded_email = urllib.parse.quote(self.email)
            encoded_password = urllib.parse.quote(self.mail_pass)
            url = f"https://api.firstmail.ltd/v1/market/get/message?username={encoded_email}&password={encoded_password}"
            headers = {"accept": "application/json", "X-API-KEY": FIRSTMAIL_API_KEY}
            for attempt in range(max_attempts):
                try:
                    response = requests.get(url, headers=headers, timeout=35)
                    if response.status_code == 200:
                        try:
                            messages = response.json()
                            self.log(f"Ответ API: {json.dumps(messages, indent=2)}", Fore.YELLOW)
                        except ValueError as e:
                            self.log(f"Некорректный JSON: {response.text}", Fore.YELLOW)
                            await asyncio.sleep(delay)
                            continue
                        msg_body = ''
                        is_from_tiktok = False
                        if isinstance(messages, dict):
                            if not messages.get("has_message", False):
                                self.log(f"Попытка {attempt + 1}/{max_attempts}: писем нет, ждем {delay} сек...", Fore.YELLOW)
                                await asyncio.sleep(delay)
                                continue
                            from_field = messages.get('from', '')
                            subject = messages.get('subject', '')
                            if ('TikTok' in from_field or 'tiktok' in from_field.lower() or
                                'TikTok' in subject or 'tiktok' in subject.lower()):
                                is_from_tiktok = True
                            msg_body = (messages.get('message', '') or messages.get('body', '') or
                                        messages.get('text', '') or messages.get('content', '') or
                                        messages.get('html', ''))
                        elif isinstance(messages, list):
                            messages.sort(key=lambda x: x.get('date', ''), reverse=True)
                            for msg in messages:
                                from_field = msg.get('from', '')
                                subject = msg.get('subject', '')
                                if ('TikTok' in from_field or 'tiktok' in from_field.lower() or
                                    'TikTok' in subject or 'tiktok' in subject.lower()):
                                    msg_body = (msg.get('message', '') or msg.get('body', '') or
                                                msg.get('text', '') or msg.get('content', '') or
                                                msg.get('html', ''))
                                    is_from_tiktok = True
                                    break
                        if is_from_tiktok and msg_body:
                            self.log(f"Тело письма: {msg_body}", Fore.YELLOW)
                            code_match = re.search(r'\b\d{6}\b|\[\d{6}\]|\d{3}\s*\d{3}', msg_body)
                            if code_match:
                                code = code_match.group(0).strip('[]').replace(' ', '')
                                self.log(f"Код найден: {code}", Fore.GREEN)
                                return code
                        self.log(f"Попытка {attempt + 1}/{max_attempts}: код не найден, ждем {delay} сек...", Fore.YELLOW)
                        await asyncio.sleep(delay)
                    else:
                        self.log(f"Ошибка API, статус: {response.status_code}, ответ: {response.text}", Fore.YELLOW)
                        await asyncio.sleep(delay)
                except requests.exceptions.RequestException as e:
                    self.log(f"Ошибка запроса к Firstmail (попытка {attempt + 1}): {e}", Fore.YELLOW)
                    await asyncio.sleep(delay)
                except Exception as e:
                    self.log(f"Неожиданная ошибка (попытка {attempt + 1}): {e}", Fore.YELLOW)
                    await asyncio.sleep(delay)
            self.log("Код не найден в письмах после всех попыток", Fore.YELLOW)
            return None
        except Exception as e:
            self.log(f"Критическая ошибка Firstmail: {e}", Fore.YELLOW)
            return None

    async def human_type(self, selector: str, text: str):
        """Эмуляция человеческого ввода текста с рандомными задержками"""
        try:
            if await self.page.is_closed():
                self.log("Страница закрыта, попытка ввода текста невозможна", Fore.YELLOW)
                return
            element = await self.page.wait_for_selector(selector, timeout=15000)
            await element.click()
            await self.page.mouse.move(random.randint(100, 500), random.randint(100, 500), steps=10)
            await element.fill('')
            await asyncio.sleep(random.uniform(0.5, 1.5))
            for char in text:
                await element.type(char, delay=random.uniform(0.15, 0.35))
                if random.random() < 0.1:
                    await asyncio.sleep(random.uniform(0.5, 1.0))
        except Exception as e:
            self.log(f"Ошибка в human_type: {e}", Fore.YELLOW)
            try:
                await self.page.evaluate(f"""document.querySelector('{selector}').value = '{text.replace("'", "\\'")}'""")
            except Exception as e2:
                self.log(f"Ошибка резервного ввода: {e2}", Fore.YELLOW)

    async def safe_click(self, selector: str, description: str = ""):
        """Безопасный клик по элементу с рандомными задержками"""
        try:
            if await self.page.is_closed():
                self.log("Страница закрыта, клик невозможен", Fore.YELLOW)
                return False
            element = await self.page.wait_for_selector(selector, timeout=25000)
            await self.page.evaluate("el => el.scrollIntoView({block: 'center'})", element)
            await asyncio.sleep(random.uniform(0.5, 1.0))
            await element.hover()
            await asyncio.sleep(random.uniform(0.3, 0.6))
            await element.click()
            if description:
                self.log(f"Клик: {description}", Fore.GREEN)
            return True
        except Exception as e:
            if description:
                self.log(f"Ошибка клика на {description}: {e}", Fore.YELLOW)
            try:
                await self.page.evaluate(f"document.querySelector('{selector}').click()")
                return True
            except Exception as e2:
                self.log(f"Вторая ошибка клика: {e2}", Fore.YELLOW)
                return False

    async def click_by_coordinates(self, x: int, y: int, description: str = ""):
        """Клик по координатам с рандомными задержками"""
        try:
            if await self.page.is_closed():
                self.log("Страница закрыта, клик невозможен", Fore.YELLOW)
                return False
            await self.page.mouse.move(x, y, steps=random.randint(5, 15))
            await asyncio.sleep(random.uniform(0.3, 0.7))
            await self.page.mouse.click(x, y)
            await self.page.mouse.move(0, 0, steps=random.randint(5, 15))
            if description:
                self.log(f"Клик по координатам: {description} ({x}, {y})", Fore.GREEN)
            return True
        except Exception as e:
            if description:
                self.log(f"Ошибка клика по координатам {description}: {e}", Fore.YELLOW)
            return False

    async def click_checkbox_combined(self):
        """Комбинированный метод для клика по чекбоксу согласия"""
        try:
            if await self.click_by_coordinates(*CHECKBOX_COORDINATES, "Чекбокс по координатам"):
                return True
            if await self.page.is_closed():
                self.log("Страница закрыта, клик невозможен", Fore.YELLOW)
                return False
            text_elements = await self.page.query_selector_all(
                '//*[contains(text(), "Get trending content") or contains(text(), "newsletters") or contains(text(), "promotions")]'
            )
            if text_elements:
                for element in text_elements:
                    bounding_box = await element.bounding_box()
                    if bounding_box:
                        x = bounding_box['x'] - 20
                        y = bounding_box['y'] + bounding_box['height'] / 2
                        if await self.click_by_coordinates(int(x), int(y), "Чекбокс рядом с текстом"):
                            return True
        except Exception as e:
            self.log(f"Ошибка в click_checkbox_combined: {e}", Fore.YELLOW)
        return False

    async def select_date_with_precise_selectors(self):
        """Заполнение даты рождения с точными селекторами"""
        try:
            if await self.page.is_closed():
                self.log("Страница закрыта, выбор даты невозможен", Fore.YELLOW)
                return False
            await self.page.wait_for_selector('//div[contains(@class, "tiktok-1leicpq-DivSelectLabel")]', timeout=15000)
            date_dropdowns = await self.page.query_selector_all('//div[contains(@class, "tiktok-1leicpq-DivSelectLabel")]')
            self.log(f"Найдено выпадающих списков для даты: {len(date_dropdowns)}", Fore.YELLOW)
            if len(date_dropdowns) >= 3:
                await date_dropdowns[0].click()
                await asyncio.sleep(random.uniform(1.0, 2.0))
                month_options = await self.page.query_selector_all('//div[contains(@class, "tiktok-x376y3-DivOption")]')
                if month_options:
                    month_texts = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
                    valid_months = []
                    for opt in month_options:
                        text = await opt.inner_text()
                        if any(month in text for month in month_texts):
                            valid_months.append(opt)
                    if valid_months:
                        await random.choice(valid_months).click()
                        self.log("Месяц выбран", Fore.GREEN)
                await asyncio.sleep(random.uniform(1.0, 2.0))
                await date_dropdowns[1].click()
                await asyncio.sleep(random.uniform(1.0, 2.0))
                day_options = await self.page.query_selector_all('//div[contains(@class, "tiktok-x376y3-DivOption")]')
                if day_options:
                    valid_days = []
                    for opt in day_options:
                        text = await opt.inner_text()
                        if text.isdigit() and 1 <= int(text) <= 31:
                            valid_days.append(opt)
                    if valid_days:
                        await random.choice(valid_days[:28]).click()
                        self.log("День выбран", Fore.GREEN)
                await asyncio.sleep(random.uniform(1.0, 2.0))
                await date_dropdowns[2].click()
                await asyncio.sleep(random.uniform(1.0, 2.0))
                year_options = await self.page.query_selector_all('//div[contains(@class, "tiktok-x376y3-DivOption")]')
                if year_options:
                    valid_years = []
                    for opt in year_options:
                        text = await opt.inner_text()
                        if text.isdigit() and 1980 <= int(text) <= 2000:
                            valid_years.append(opt)
                    if valid_years:
                        await random.choice(valid_years).click()
                        self.log("Год выбран", Fore.GREEN)
                return True
        except Exception as e:
            self.log(f"Ошибка заполнения даты: {e}", Fore.YELLOW)
            return False
        return False

    async def register(self):
        """Процесс регистрации аккаунта TikTok"""
        async with async_playwright() as playwright:
            if not await self.setup_browser(playwright):
                return False
            try:
                await self.page.wait_for_load_state('domcontentloaded', timeout=60000)
                await self.page.goto('https://www.tiktok.com/signup', timeout=60000)
                current_url = self.page.url
                self.log(f"Перешли на URL: {current_url}", Fore.GREEN)
                page_content = await self.page.content()
                if '502 Bad Gateway' in page_content:
                    self.log("Обнаружена ошибка 502 Bad Gateway", Fore.YELLOW)
                    try:
                        with open(f"502_error_{self.email}.html", "w", encoding="utf-8") as f:
                            f.write(page_content)
                        await self.page.screenshot(path=f"502_screenshot_{self.email}.png")
                    except Exception:
                        pass
                    return False
                await asyncio.sleep(random.uniform(5, 7))
                phone_email_selector = '//div[contains(text(), "Use phone or email") or contains(text(), "Введите телефон или эл. почту") or @style="font-size: 15px;"]'
                if not await self.safe_click(phone_email_selector, "Использовать телефон или email"):
                    self.log("Не удалось кликнуть 'Использовать телефон или email'", Fore.YELLOW)
                    try:
                        await self.page.screenshot(path=f"phone_email_error_{self.email}.png")
                    except Exception:
                        pass
                    return False
                await asyncio.sleep(random.uniform(5, 7))
                email_signup_selector = '//a[contains(@href, "/signup/phone-or-email/email") or contains(text(), "Sign up with email") or contains(text(), "Зарегистрироваться через эл. почту") or @class="ep888o80 tiktok-1mgli76-ALink-StyledLink epl6mg0"]'
                if not await self.safe_click(email_signup_selector, "Зарегистрироваться через email"):
                    self.log("Не удалось кликнуть 'Зарегистрироваться через email'", Fore.YELLOW)
                    try:
                        await self.page.screenshot(path=f"email_signup_error_{self.email}.png")
                    except Exception:
                        pass
                    return False
                await asyncio.sleep(random.uniform(5, 7))
                for attempt in range(MAX_RETRIES):
                    try:
                        await self.page.wait_for_selector('body', timeout=25000)
                        await asyncio.sleep(random.uniform(3, 5))
                        self.log("Заполняем дату рождения...", Fore.YELLOW)
                        if not await self.select_date_with_precise_selectors():
                            self.log("Ошибка заполнения даты", Fore.YELLOW)
                            continue
                        await asyncio.sleep(random.uniform(2, 4))
                        self.log("Заполняем email...", Fore.YELLOW)
                        email_selector = '//input[contains(@placeholder, "Email")] | //input[@type="email"] | //input[contains(@name, "email")]'
                        await self.human_type(email_selector, self.email)
                        self.log("Email заполнен", Fore.GREEN)
                        await asyncio.sleep(random.uniform(2, 4))
                        self.log("Заполняем пароль...", Fore.YELLOW)
                        password_selector = '//input[contains(@placeholder, "Password")] | //input[@type="password"] | //input[contains(@name, "password")]'
                        await self.human_type(password_selector, self.tikTokPassword)
                        self.log(f"Пароль заполнен: {self.tikTokPassword}", Fore.GREEN)
                        await asyncio.sleep(random.uniform(2, 4))
                        self.log("Отмечаем чекбокс согласия...", Fore.YELLOW)
                        if not await self.click_checkbox_combined():
                            self.log("Не удалось отметить чекбокс, продолжаем...", Fore.YELLOW)
                        await asyncio.sleep(random.uniform(2, 4))
                        self.log("Нажимаем кнопку отправки кода...", Fore.YELLOW)
                        send_button_selector = '//button[contains(text(), "Send code")] | //button[contains(text(), "Next")] | //div[contains(text(), "Send code")] | //button[@type="submit"]'
                        await self.safe_click(send_button_selector, "Кнопка отправки кода")
                        self.log("Код отправлен на email", Fore.GREEN)
                        await asyncio.sleep(random.uniform(10, 15))
                        code = await self.get_firstmail_code()
                        if not code:
                            self.log("Не удалось получить код из почты", Fore.YELLOW)
                            continue
                        self.log("Вводим код верификации...", Fore.YELLOW)
                        code_selector = '//input[contains(@placeholder, "code")] | //input[@inputmode="numeric"] | //input[contains(@name, "code")]'
                        await self.human_type(code_selector, code)
                        self.log("Код введен", Fore.GREEN)
                        await asyncio.sleep(random.uniform(3, 5))
                        self.log("Подтверждаем регистрацию...", Fore.YELLOW)
                        confirm_button_selector = '//button[contains(text(), "Next")] | //button[contains(text(), "Confirm")] | //button[contains(text(), "Verify")]'
                        await self.safe_click(confirm_button_selector, "Кнопка подтверждения")
                        await asyncio.sleep(random.uniform(6, 10))
                        current_url = self.page.url
                        if 'signup/create-username' in current_url:
                            self.log("На странице выбора имени пользователя", Fore.YELLOW)
                            username_selector = 'input[name="new-username"], input.tiktok-11to27l-InputContainer, input[placeholder="Ім’я користувача"]'
                            await self.human_type(username_selector, self.username)
                            self.log(f"Введено имя пользователя: {self.username}", Fore.GREEN)
                            await asyncio.sleep(random.uniform(1.5, 3))
                            next_button_selector = '//button[contains(text(), "Next") or contains(text(), "Continue") or @type="submit"]'
                            await self.safe_click(next_button_selector, "Кнопка после имени пользователя")
                            await asyncio.sleep(random.uniform(6, 10))
                        current_url = self.page.url
                        if 'foryou' in current_url or 'profile' in current_url or 'signup' not in current_url:
                            self.is_registered = True
                            self.log("Аккаунт успешно зарегистрирован!", Fore.GREEN)
                            return True
                        else:
                            self.log(f"Возможная ошибка регистрации, URL: {current_url}", Fore.YELLOW)
                            try:
                                await self.page.screenshot(path=f"debug_{self.email}.png")
                            except Exception:
                                pass
                            continue
                    except Exception as e:
                        self.log(f"Ошибка на попытке {attempt + 1}: {e}", Fore.YELLOW)
                        try:
                            await self.page.screenshot(path=f"error_{self.email}_attempt_{attempt}.png")
                        except Exception:
                            pass
                        if attempt < MAX_RETRIES - 1:
                            self.log(f"Ждем {RETRY_DELAY} секунд перед повторной попыткой...", Fore.YELLOW)
                            await self.page.reload()
                            await asyncio.sleep(random.uniform(5, 7))
                        continue
                return False
            except Exception as e:
                self.log(f"Критическая ошибка: {e}", Fore.YELLOW)
                try:
                    await self.page.screenshot(path=f"critical_error_{self.email}.png")
                except Exception:
                    pass
                return False
            finally:
                await self.cleanup()

async def main():
    """Основная функция для запуска процесса регистрации"""
    print(Fore.CYAN + "=== TikTok Auto Register (Dolphin Anty) ===")
    print("Введите данные почты в формате: email:mail_password")
    print("Пароль почты только для API, пароль TikTok генерируется отдельно!")
    print("Введите 'START' для начала")
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
    print(Fore.YELLOW + f"Начинаем регистрацию {len(accounts)} аккаунтов...")
    registered_accounts = []
    for i, (email, mail_pass) in enumerate(accounts):
        print(Fore.CYAN + f"\n=== Регистрация {i + 1}/{len(accounts)} ===")
        register = TikTokAutoRegister(email, mail_pass)
        if await register.register():
            output = f"{email}:{mail_pass}:{register.tikTokPassword}:{register.username}"
            registered_accounts.append(output)
            print(Fore.GREEN + f"Успех: {output}")
            with open("registered_accounts.txt", "a", encoding="utf-8") as f:
                f.write(output + "\n")
        else:
            print(Fore.RED + f"Не удалось зарегистрировать {email}")
        if i < len(accounts) - 1:
            pause_time = random.randint(60, 120)
            print(Fore.YELLOW + f"Ждем {pause_time} секунд перед следующим аккаунтом...")
            await asyncio.sleep(pause_time)
    if registered_accounts:
        print(Fore.CYAN + "\nВсе зарегистрированные аккаунты:")
        for acc in registered_accounts:
            print(acc)
        print(Fore.GREEN + "Данные сохранены в registered_accounts.txt")

if __name__ == "__main__":
    asyncio.run(main())