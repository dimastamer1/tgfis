from aiohttp import web
import aiohttp_jinja2
import jinja2
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'static')

app = web.Application()

# Настраиваем Jinja2
aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(STATIC_DIR))

# Отдаём index.html по корню
@aiohttp_jinja2.template('index.html')
async def handle_index(request):
    return {}

# Статика
app.router.add_static('/static/', STATIC_DIR, show_index=True)
app.router.add_get('/', handle_index)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))  # Render использует переменную PORT
    web.run_app(app, host='0.0.0.0', port=port)
