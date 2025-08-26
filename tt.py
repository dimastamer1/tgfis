
import asyncio
import requests
import random
import time
import re
import string
import os
import psutil
from colorama import Fore, Style, init
from playwright.async_api import async_playwright, Playwright, BrowserContext
import urllib.parse
import json
from twocaptcha import TwoCaptcha  # Для автоматического решения CAPTCHA

# Инициализация colorama для цветного вывода
init(autoreset=True)

# ========== КОНФИГУРАЦИЯ ==========
FIRSTMAIL_API_KEY = "40512629-2f17-4aa9-8cc9-cf12d0fc53c0"
TWOCAPTCHA_API_KEY = "ВАШ_КЛЮЧ_2CAPTCHA"  # Замени на свой ключ 2Captcha
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]
MAX_RETRIES = 3
RETRY_DELAY = 60
CHECKBOX_COORDINATES = (784, 609)  # Настрой координаты под свое разрешение экрана
CHROME_EXECUTABLE_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"  # Путь к твоему Chrome

async def kill_browser_processes():
    """Убиваем все процессы Chrome перед новым запуском"""
    try:
        browser_processes = ['chrome.exe', 'msedge.exe']
        for proc in psutil.process_iter(['name']):
            if proc.info['name'] and any(name in proc.info['name'].lower() for name in browser_processes):
                try:
                    proc.kill()
                except psutil.NoSuchProcess:
                    pass
                except Exception as e:
                    print(f"Ошибка при завершении процесса {proc.info['name']}: {e}")
        await asyncio.sleep(2)
    except Exception as e:
        print(f"Ошибка в kill_browser_processes: {e}")

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
        self.user_agent = random.choice(USER_AGENTS)

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
        """Настройка Playwright с использованием установленного Google Chrome"""
        await kill_browser_processes()
        try:
            browser = await playwright.chromium.launch(
                executable_path=CHROME_EXECUTABLE_PATH,  # Используем установленный Chrome
                headless=False,  # Видимый режим
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    f'--user-agent={self.user_agent}',
                    '--disable-extensions',  # Отключаем расширения для чистоты
                    '--start-maximized'  # Запускаем в развернутом окне
                ]
            )
            context = await browser.new_context(
                user_agent=self.user_agent,
                viewport={'width': 1920, 'height': 1080},
                locale='en-US',
                timezone_id='America/New_York',
                java_script_enabled=True,
                bypass_csp=True,
                permissions=['geolocation'],
                screen={'width': 1920, 'height': 1080},
                device_scale_factor=1
            )
            # Усиливаем антидетект
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
                Object.defineProperty(navigator, 'vendor', { get: () => 'Google Inc.' });
                Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 4 });
                Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
                Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });
                Object.defineProperty(window, 'outerWidth', { get: () => 1920 });
                Object.defineProperty(window, 'outerHeight', { get: () => 1080 });
                const getParameter = WebGLRenderingContext.prototype.getParameter;
                WebGLRenderingContext.prototype.getParameter = function(parameter) {
                    if (parameter === 37445) return 'Google Inc.';
                    if (parameter === 37446) return 'ANGLE (Intel, Intel(R) UHD Graphics 630, Direct3D11)';
                    return getParameter.apply(this, arguments);
                };
                const ctx = HTMLCanvasElement.prototype.getContext;
                HTMLCanvasElement.prototype.getContext = function(type) {
                    const context = ctx.apply(this, arguments);
                    if (type === '2d') {
                        const getImageData = context.getImageData;
                        context.getImageData = function(...args) {
                            const data = getImageData.apply(this, args);
                            const pixels = data.data;
                            for (let i = 0; i < pixels.length; i += 4) {
                                pixels[i] = pixels[i] ^ (Math.random() * 2);
                                pixels[i + 1] = pixels[i + 1] ^ (Math.random() * 2);
                                pixels[i + 2] = pixels[i + 2] ^ (Math.random() * 2);
                            }
                            return data;
                        };
                    }
                    return context;
                };
            """)
            self.context = context
            self.page = await context.new_page()
            await self.page.route('**/*', self.log_network)
            await self.clean_browser_data()
            self.log("Браузер настроен (Google Chrome)", Fore.GREEN)
            return True
        except Exception as e:
            self.log(f"Ошибка настройки браузера: {e}", Fore.RED)
            return False

    async def log_network(self, route):
        """Логирование сетевых запросов и ответов"""
        try:
            response = await route.fetch()
            status = response.status
            url = route.request.url
            self.log(f"Запрос: {url} | Статус: {status}", Fore.YELLOW)
            if status in [502, 429]:
                self.log(f"Ошибка {status} на {url}", Fore.RED)
            await route.continue_()
        except Exception as e:
            self.log(f"Ошибка перехвата сети: {e}", Fore.RED)
            await route.continue_()

    async def clean_browser_data(self):
        """Очистка куки, кэша, локального и сессионного хранилища"""
        try:
            await self.context.clear_cookies()
            await self.context.clear_permissions()
            await self.page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
            self.log("Данные браузера очищены (куки, кэш, хранилища)", Fore.GREEN)
        except Exception as e:
            self.log(f"Ошибка очистки данных браузера: {e}", Fore.RED)

    async def cleanup(self):
        """Очистка ресурсов после работы"""
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
        except Exception as e:
            self.log(f"Ошибка очистки контекста браузера: {e}", Fore.RED)
        finally:
            await kill_browser_processes()

    async def get_firstmail_code(self, max_attempts=12, delay=10) -> str | None:
        """Получение кода верификации от Firstmail"""
        self.log(f"Получение кода от Firstmail для {self.email} (макс. {max_attempts} попыток)...", Fore.YELLOW)
        try:
            encoded_email = urllib.parse.quote(self.email)
            encoded_password = urllib.parse.quote(self.mail_pass)
            url = f"https://api.firstmail.ltd/v1/market/get/message?username={encoded_email}&password={encoded_password}"
            headers = {"accept": "application/json", "X-API-KEY": FIRSTMAIL_API_KEY, "User-Agent": self.user_agent}
            for attempt in range(max_attempts):
                try:
                    response = requests.get(url, headers=headers, timeout=35)
                    if response.status_code == 200:
                        try:
                            messages = response.json()
                            self.log(f"Ответ API: {json.dumps(messages, indent=2)}", Fore.YELLOW)
                        except ValueError as e:
                            self.log(f"Некорректный JSON: {response.text}", Fore.RED)
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
                        self.log(f"Ошибка API, статус: {response.status_code}, ответ: {response.text}", Fore.RED)
                        await asyncio.sleep(delay)
                except requests.exceptions.RequestException as e:
                    self.log(f"Ошибка запроса к Firstmail (попытка {attempt + 1}): {e}", Fore.RED)
                    await asyncio.sleep(delay)
                except Exception as e:
                    self.log(f"Неожиданная ошибка (попытка {attempt + 1}): {e}", Fore.RED)
                    await asyncio.sleep(delay)
            self.log("Код не найден в письмах после всех попыток", Fore.RED)
            return None
        except Exception as e:
            self.log(f"Критическая ошибка Firstmail: {e}", Fore.RED)
            return None

    async def human_type(self, selector: str, text: str):
        """Эмуляция человеческого ввода текста с рандомными задержками"""
        try:
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
            self.log(f"Ошибка в human_type: {e}", Fore.RED)
            await self.page.evaluate(f"""document.querySelector('{selector}').value = '{text.replace("'", "\\'")}'""")

    async def safe_click(self, selector: str, description: str = ""):
        """Безопасный клик по элементу с обработкой ошибок и рандомными задержками"""
        try:
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
                self.log(f"Ошибка клика на {description}: {e}", Fore.RED)
            try:
                await self.page.evaluate(f"document.querySelector('{selector}').click()")
                return True
            except Exception as e2:
                self.log(f"Вторая ошибка клика: {e2}", Fore.RED)
                return False

    async def click_by_coordinates(self, x: int, y: int, description: str = ""):
        """Клик по координатам с рандомными задержками"""
        try:
            await self.page.mouse.move(x, y, steps=random.randint(5, 15))
            await asyncio.sleep(random.uniform(0.3, 0.7))
            await self.page.mouse.click(x, y)
            await self.page.mouse.move(0, 0, steps=random.randint(5, 15))
            if description:
                self.log(f"Клик по координатам: {description} ({x}, {y})", Fore.GREEN)
            return True
        except Exception as e:
            if description:
                self.log(f"Ошибка клика по координатам {description}: {e}", Fore.RED)
            return False

    async def click_checkbox_combined(self):
        """Комбинированный метод для клика по чекбоксу согласия"""
        if await self.click_by_coordinates(*CHECKBOX_COORDINATES, "Чекбокс по координатам"):
            return True
        try:
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
            self.log(f"Ошибка в click_checkbox_combined: {e}", Fore.RED)
        return False

    async def select_date_with_precise_selectors(self):
        """Заполнение даты рождения с точными селекторами"""
        try:
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
            self.log(f"Ошибка заполнения даты: {e}", Fore.RED)
            return False
        return False

    async def check_captcha(self):
        """Проверка наличия CAPTCHA"""
        captcha_selectors = [
            'div.captcha_verify_container',
            'iframe[src*="captcha"]',
            'div[id*="captcha"]',
            'div[class*="verify"]'
        ]
        for selector in captcha_selectors:
            try:
                await self.page.wait_for_selector(selector, timeout=5000)
                self.log("Обнаружена CAPTCHA!", Fore.RED)
                return True
            except:
                continue
        return False

    async def solve_captcha(self):
        """Автоматическое решение CAPTCHA через 2Captcha"""
        try:
            solver = TwoCaptcha(TWOCAPTCHA_API_KEY)
            # Получаем sitekey для CAPTCHA
            sitekey = await self.page.evaluate("document.querySelector('iframe[src*=\"captcha\"]')?.src.match(/k=([^&]+)/)?.[1] || ''")
            if not sitekey:
                self.log("Sitekey для CAPTCHA не найден, попробуем вручную", Fore.RED)
                return False
            self.log(f"Sitekey CAPTCHA: {sitekey}", Fore.YELLOW)
            result = solver.recaptcha(sitekey=sitekey, url='https://www.tiktok.com/signup')
            code = result['code']
            self.log(f"CAPTCHA решена: {code}", Fore.GREEN)
            await self.page.evaluate(f"""
                document.querySelector('textarea[id="g-recaptcha-response"]').value = '{code}';
                window.___grecaptcha_cfg.clients[0].callback('{code}');
            """)
            await asyncio.sleep(random.uniform(2, 4))
            return True
        except Exception as e:
            self.log(f"Ошибка решения CAPTCHA: {e}", Fore.RED)
            return False

    async def register(self):
        """Процесс регистрации аккаунта TikTok"""
        async with async_playwright() as playwright:
            if not await self.setup_browser(playwright):
                return False
            try:
                await self.page.goto('https://www.tiktok.com/signup', timeout=60000)
                current_url = self.page.url
                self.log(f"Перешли на URL: {current_url}", Fore.GREEN)
                page_content = await self.page.content()
                if '502 Bad Gateway' in page_content:
                    self.log("Обнаружена ошибка 502 Bad Gateway", Fore.RED)
                    with open(f"502_error_{self.email}.html", "w", encoding="utf-8") as f:
                        f.write(page_content)
                    await self.page.screenshot(path=f"502_screenshot_{self.email}.png")
                    return False
                await asyncio.sleep(random.uniform(5, 7))

                phone_email_selector = '//div[contains(text(), "Use phone or email") or contains(text(), "Введите телефон или эл. почту") or @style="font-size: 15px;"]'
                if not await self.safe_click(phone_email_selector, "Использовать телефон или email"):
                    self.log("Не удалось кликнуть 'Использовать телефон или email'", Fore.RED)
                    await self.page.screenshot(path=f"phone_email_error_{self.email}.png")
                    return False
                await asyncio.sleep(random.uniform(5, 7))

                email_signup_selector = '//a[contains(@href, "/signup/phone-or-email/email") or contains(text(), "Sign up with email") or contains(text(), "Зарегистрироваться через эл. почту") or @class="ep888o80 tiktok-1mgli76-ALink-StyledLink epl6mg0"]'
                if not await self.safe_click(email_signup_selector, "Зарегистрироваться через email"):
                    self.log("Не удалось кликнуть 'Зарегистрироваться через email'", Fore.RED)
                    await self.page.screenshot(path=f"email_signup_error_{self.email}.png")
                    return False
                await asyncio.sleep(random.uniform(5, 7))

                if await self.check_captcha():
                    self.log("Обнаружена CAPTCHA, пытаемся решить автоматически...", Fore.YELLOW)
                    if not await self.solve_captcha():
                        self.log("Не удалось решить CAPTCHA автоматически, решите вручную и нажмите Enter...", Fore.RED)
                        input("Нажмите Enter после решения CAPTCHA...")
                    else:
                        self.log("CAPTCHA решена автоматически", Fore.GREEN)

                for attempt in range(MAX_RETRIES):
                    try:
                        await self.page.wait_for_selector('body', timeout=25000)
                        await asyncio.sleep(random.uniform(3, 5))
                        self.log("Заполняем дату рождения...", Fore.YELLOW)
                        if not await self.select_date_with_precise_selectors():
                            self.log("Ошибка заполнения даты", Fore.RED)
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
                            self.log("Не удалось получить код из почты", Fore.RED)
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
                            await self.page.screenshot(path=f"debug_{self.email}.png")
                            continue
                    except Exception as e:
                        self.log(f"Ошибка на попытке {attempt + 1}: {e}", Fore.RED)
                        await self.page.screenshot(path=f"error_{self.email}_attempt_{attempt}.png")
                        if attempt < MAX_RETRIES - 1:
                            self.log(f"Ждем {RETRY_DELAY} секунд перед повторной попыткой...", Fore.YELLOW)
                            await self.page.reload()
                            await asyncio.sleep(random.uniform(5, 7))
                        continue
                return False
            except Exception as e:
                self.log(f"Критическая ошибка: {e}", Fore.RED)
                await self.page.screenshot(path=f"critical_error_{self.email}.png")
                return False
            finally:
                await self.cleanup()

async def main():
    """Основная функция для запуска процесса регистрации"""
    print(Fore.CYAN + "=== TikTok Auto Register (Google Chrome) ===")
    print("Введите данные почты в формате: email:mail_password")
    print("Пароль почты только для API, пароль TikTok генерируется отдельно!")
    print("Введите 'START' для начала")
    await kill_browser_processes()
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
            pause_time = random.randint(60, 120)  # Увеличенная пауза между аккаунтами
            print(Fore.YELLOW + f"Ждем {pause_time} секунд перед следующим аккаунтом...")
            await asyncio.sleep(pause_time)
    if registered_accounts:
        print(Fore.CYAN + "\nВсе зарегистрированные аккаунты:")
        for acc in registered_accounts:
            print(acc)
        print(Fore.GREEN + "Данные сохранены в registered_accounts.txt")

if __name__ == "__main__":
    asyncio.run(main())
