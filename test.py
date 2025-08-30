import asyncio
import sys

try:
    from playwright.async_api import async_playwright
    print("Playwright успешно импортирован!")
except ImportError as e:
    print(f"Ошибка импорта Playwright: {e}")
    print("Установите Playwright с помощью: pip install playwright")
    print("После установки выполните: playwright install")
    sys.exit(1)

async def open_browser():
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=False)
            print("Браузер успешно открыт! Оставляю открытым на 10 секунд для тестов...")
            await asyncio.sleep(10)
            await browser.close()
            print("Браузер закрыт.")
    except Exception as e:
        print(f"Ошибка при открытии браузера: {e}")

if __name__ == "__main__":
    asyncio.run(open_browser())