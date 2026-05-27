import asyncio
import logging
import os
import sys

# Принудительно выставляем UTF-8 для всех потоков ввода/вывода.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("LANG", "C.UTF-8")

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from handlers import start, transactions, stats, ai_advisor, plan, payments, referrals, categories, recurring
from handlers import admin as admin_handlers
from middleware import BanAndFloodMiddleware
from api.server import app as fastapi_app
from services.storage import init_db
from services.scheduler import scheduler_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Порт для FastAPI Mini App — берётся из env PORT (Replit) или дефолт 5000
FASTAPI_PORT = int(os.getenv("PORT", 5000))


async def run_bot():
    """Запускает Telegram-бот в режиме polling + фоновый scheduler."""
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise ValueError("BOT_TOKEN не найден. Добавь его в Secrets.")

    bot = Bot(token=bot_token)

    # FSM-стейт переживает рестарт через Redis. Если REDIS_URL не задан или
    # подключение падает — фолбэк на MemoryStorage, чтобы прод не лёг.
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        storage = RedisStorage.from_url(redis_url)
        logger.info(f"FSM storage: Redis ({redis_url})")
    except Exception as e:
        logger.warning(f"Redis storage init failed ({e}); falling back to MemoryStorage")
        storage = MemoryStorage()

    dp = Dispatcher(storage=storage)

    # Anti-flood + ban-check на каждое входящее сообщение
    dp.message.middleware(BanAndFloodMiddleware())

    # Порядок роутеров важен: ai_advisor идёт до transactions;
    # payments — отдельным роутером, чтобы pre_checkout_query и successful_payment
    # обрабатывались первыми. admin — рано, чтобы /ban /unban /admin_stats не съел кто-то ниже.
    dp.include_router(payments.router)
    dp.include_router(admin_handlers.router)
    dp.include_router(start.router)
    dp.include_router(referrals.router)
    dp.include_router(categories.router)
    dp.include_router(recurring.router)
    dp.include_router(plan.router)
    dp.include_router(ai_advisor.router)
    dp.include_router(stats.router)
    dp.include_router(transactions.router)

    # Фоновый шедулер (trial sweep + ежедневные напоминания)
    asyncio.create_task(scheduler_loop(bot))

    logger.info("Telegram-бот запускается в режиме polling...")
    await dp.start_polling(bot)


async def run_api():
    """Запускает FastAPI-сервер для Mini App."""
    config = uvicorn.Config(
        fastapi_app,
        host="127.0.0.1",
        port=FASTAPI_PORT,
        log_level="info",
    )
    server = uvicorn.Server(config)
    logger.info(f"Mini App API запускается на порту {FASTAPI_PORT}...")
    await server.serve()


async def main():
    """Запускает бот и FastAPI-сервер параллельно в одном event loop."""
    init_db()
    await asyncio.gather(run_bot(), run_api())


if __name__ == "__main__":
    asyncio.run(main())
