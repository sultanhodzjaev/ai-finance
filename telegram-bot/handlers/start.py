import logging
import os

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
)

from services import storage

logger = logging.getLogger(__name__)
router = Router()

# URL Mini App — берём из переменной окружения WEBAPP_URL,
# или вычисляем автоматически из REPLIT_DOMAINS (формат: domain1,domain2,...)
def _get_webapp_url() -> str:
    explicit = os.getenv("WEBAPP_URL", "")
    if explicit:
        return explicit
    domains = os.getenv("REPLIT_DOMAINS", "")
    if domains:
        first_domain = domains.split(",")[0].strip()
        return f"https://{first_domain}/miniapp"
    return ""


def get_main_menu() -> InlineKeyboardMarkup:
    """Возвращает главное меню с кнопкой открытия Mini App."""
    webapp_url = _get_webapp_url()
    buttons = []

    # Кнопка Mini App — если URL доступен
    if webapp_url:
        buttons.append([
            InlineKeyboardButton(
                text="📲 Открыть приложение",
                web_app=WebAppInfo(url=webapp_url),
            )
        ])

    buttons += [
        [
            InlineKeyboardButton(text="💬 Спросить финансиста", callback_data="ask_advisor"),
            InlineKeyboardButton(text="📊 Статистика",          callback_data="show_stats"),
        ],
        [
            InlineKeyboardButton(text="📅 За сегодня", callback_data="show_today"),
            InlineKeyboardButton(text="❓ Помощь",     callback_data="show_help"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обрабатывает /start — регистрирует пользователя и показывает главное меню."""
    user = message.from_user
    first_name = user.first_name or "Друг"

    storage.get_or_create_user(
        telegram_id=user.id,
        username=user.username or "",
        first_name=first_name,
    )

    webapp_url = _get_webapp_url()
    webapp_note = "\n• 📲 Полноценный дашборд в Mini App — кнопка выше" if webapp_url else ""

    await message.answer(
        f"👋 Привет, {first_name}!\n\n"
        "Я — твой личный AI-финансист. Помогу вести учёт трат без таблиц и заморочек.\n\n"
        "🔥 Что я умею:\n"
        "• 💬 Записываю траты по текстовому сообщению («потратил 500 на обед»)\n"
        "• 📷 Распознаю чеки по фото\n"
        "• 🤖 Отвечаю на вопросы о твоих финансах\n"
        "• 📊 Показываю статистику за день, неделю, месяц"
        f"{webapp_note}\n\n"
        "Просто напиши свою первую трату или нажми кнопку ниже 👇",
        reply_markup=get_main_menu(),
    )
