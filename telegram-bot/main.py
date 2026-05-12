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

from handlers import start, transactions, stats, ai_advisor, plan, payments
from api.server import app as fastapi_app
from services.storage import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Порт для FastAPI Mini App — берётся из env PORT (Replit) или дефолт 5000
FASTAPI_PORT = int(os.getenv("PORT", 5000))


async def run_bot():
    """Запускает Telegram-бот в режиме polling."""
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise ValueError("BOT_TOKEN не найден. Добавь его в Secrets.")

    bot = Bot(token=bot_token)
    dp  = Dispatcher(storage=MemoryStorage())

    # Порядок роутеров важен: ai_advisor идёт до transactions;
    # payments — отдельным роутером, чтобы pre_checkout_query и successful_payment
    # обрабатывались первыми.
    dp.include_router(payments.router)
    dp.include_router(start.router)
    dp.include_router(plan.router)
    dp.include_router(ai_advisor.router)
    dp.include_router(stats.router)
    dp.include_router(transactions.router)

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
