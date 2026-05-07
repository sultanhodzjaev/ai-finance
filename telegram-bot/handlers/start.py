import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from services import storage

logger = logging.getLogger(__name__)
router = Router()


def get_main_menu() -> InlineKeyboardMarkup:
    """Возвращает главное меню в виде inline-кнопок."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💬 Спросить финансиста", callback_data="ask_advisor"),
            InlineKeyboardButton(text="📊 Статистика", callback_data="show_stats"),
        ],
        [
            InlineKeyboardButton(text="📅 За сегодня", callback_data="show_today"),
            InlineKeyboardButton(text="❓ Помощь", callback_data="show_help"),
        ],
    ])


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обрабатывает /start — регистрирует пользователя и показывает главное меню."""
    user = message.from_user
    first_name = user.first_name or "Друг"

    # Получаем существующего пользователя или создаём нового
    storage.get_or_create_user(
        telegram_id=user.id,
        username=user.username or "",
        first_name=first_name,
    )

    await message.answer(
        f"👋 Привет, {first_name}!\n\n"
        "Я — твой личный AI-финансист. Помогу тебе вести учёт трат без таблиц и заморочек.\n\n"
        "🔥 Что я умею:\n"
        "• 💬 Записываю траты по текстовому сообщению (\"потратил 500 на обед\")\n"
        "• 📷 Распознаю чеки по фото\n"
        "• 🤖 Отвечаю на вопросы о твоих финансах (\"где я слил больше всего в этом месяце?\")\n"
        "• 📊 Показываю статистику за день, неделю, месяц\n\n"
        "Просто напиши мне свою первую трату или нажми кнопку ниже 👇",
        reply_markup=get_main_menu(),
    )
