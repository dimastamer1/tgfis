import requests
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

# URL для GET-запроса (без automation для теста)
BASE_URL = "http://localhost:3001/v1.0/browser_profiles/653083826/start"
# Если есть API-токен, укажите его здесь
API_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiIxIiwianRpIjoiZjlhNTkzMmJhNzdiYjdhYTE5OGUzOTM3N2YyYjg5ODE5Mzc1ZDc3ZGU1MWMyYzc4MzJlZjdmZWRlYmNiYWQxYmNiZjY3MDdmZDIyMmJlY2IiLCJpYXQiOjE3NTYxOTkyNTguOTkzNzEyLCJuYmYiOjE3NTYxOTkyNTguOTkzNzE2LCJleHAiOjE3ODc3MzUyNTguOTMzODYxLCJzdWIiOiIzMDE2NDI0Iiwic2NvcGVzIjpbXSwidGVhbV9pZCI6Mjk0NTA2MywidGVhbV9wbGFuIjoiZnJlZSIsInRlYW1fcGxhbl9leHBpcmF0aW9uIjoxNzA0ODc4MjY3fQ.XZ5VtsIzWCl3IFX1uE3YvY7W-v3L80a3nj9Trdb3Hiu2-rpTCd2-5WZXpBOSNVTYQ_vA_3OzjZKHXngkFP7G4mqOA5KIayOnk-NN1HQ9GaBn03558ubhOyQUUHSp64lHMKLG6iIjzyJ0MFNzsA7BQc-NvtwdSP2MO9phK3_Ym5DW-8aMskKsLe06Eh4nogMBC8bTV3W49XpMT0wveyhj-jLK-jJCGCuX1IUUjZ47DRgWpLlLl8F6co9OpY7jo1tG59s8BCusXnxhOKx_Gvbg41tphp7oXZ8kxzOo_Fk6sTI4XpL1ynhxEIxXgQtwI34yDdroyJRhYGAD43syzGlPXW_W4_CelZpJ-rfUcRrHnIRO9fecGr1nP65rN54n-Gutoj48-LrNRBkgUd6xysRoct3Br_ONwMDMVj7I7cp-XZfoyGooOrAxi73pylvdpRW5TgnEErFJpk62_iDAbvfnkYp-1uHE1RpiLZea6IsY6bMkRfJcWdB37pR2HqnWNgvR9vEHXJEmaeszDsjKBcaVGvNSSAHpihwQFbqbAsrpkLjL6htiN9JMs93VxVW0fu_mBh63R5ff6BQsP32x-w6GQh130pbZmZET-tNnHam-oeoGEoHL1OxkoOL-A3vFal1D7DES12C18uRtfz91FeXR-eTdGK7HZfxXWXKNKCnX3vE"  # Замените на ваш токен, например: "Bearer your_api_token_here"

def start_browser_profile(url, headers=None):
    try:
        # Выполняем GET-запрос
        response = requests.get(url, headers=headers, timeout=10)
        
        # Проверяем статус ответа
        if response.status_code == 200:
            logger.info("Запрос успешно выполнен!")
            try:
                data = response.json()
                logger.info(f"Ответ сервера: {data}")
                return data
            except ValueError:
                logger.info("Ответ не содержит JSON, текст ответа: %s", response.text)
                return response.text
        else:
            logger.error("Ошибка запроса: %s (код: %d)", response.text, response.status_code)
            return None

    except requests.exceptions.ConnectionError:
        logger.error("Не удалось подключиться к серверу. Проверьте, что сервер запущен на localhost:3001")
        return None
    except requests.exceptions.Timeout:
        logger.error("Таймаут запроса. Сервер не ответил вовремя.")
        return None
    except requests.exceptions.RequestException as e:
        logger.error("Произошла ошибка при выполнении запроса: %s", str(e))
        return None

if __name__ == "__main__":
    logger.info("Запуск теста для подключения к профилю браузера...")
    
    # Формируем заголовки, если есть токен
    headers = {"Authorization": API_TOKEN} if API_TOKEN else None
    
    # Пробуем сначала с automation=1
    logger.info("Попытка с automation=1...")
    result = start_browser_profile(BASE_URL + "?automation=1", headers)
    
    # Если запрос с automation=1 не удался, пробуем без automation
    if not result:
        logger.info("Попытка без automation...")
        result = start_browser_profile(BASE_URL, headers)
    
    if result:
        logger.info("Тест завершен успешно.")
    else:
        logger.error("Тест не выполнен.")