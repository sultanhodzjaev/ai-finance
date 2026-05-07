import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from handlers import start, transactions, stats, ai_advisor

# Настройка логирования на уровне INFO
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    # Получаем токен бота из переменных окружения
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise ValueError("BOT_TOKEN не найден. Добавь его в Secrets.")

    # Создаём бота и диспетчер с FSM-хранилищем в памяти
    bot = Bot(token=bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    # Порядок роутеров важен: ai_advisor идёт до transactions,
    # чтобы FSM-состояние AdvisorStates.waiting_question перехватывалось первым.
    dp.include_router(start.router)
    dp.include_router(ai_advisor.router)
    dp.include_router(stats.router)
    dp.include_router(transactions.router)

    logger.info("Бот запускается в режиме polling...")

    # Запускаем polling (не webhook — проще для разработки на Replit)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
