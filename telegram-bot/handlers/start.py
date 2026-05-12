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
        [
            InlineKeyboardButton(text="🎁 Пригласить друга +14 дней Premium", callback_data="show_invite"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


REFERRAL_BONUS_DAYS = 14


def _parse_start_param(text: str | None) -> str:
    """Возвращает start-параметр после /start или пустую строку."""
    if not text:
        return ""
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


async def _apply_referral(new_user_id: int, ref_param: str) -> tuple[bool, str | None]:
    """
    Применяет реферал, если start-параметр начинается с ref_.
    Возвращает (applied, referrer_first_name).
    """
    if not ref_param.startswith("ref_"):
        return False, None
    code = ref_param[4:]
    if not code:
        return False, None

    user = storage.get_user(new_user_id) or {}
    if user.get("referred_by_user_id"):
        return False, None  # уже был референом — повторно не активируем

    referrer = storage.get_user_by_referral_code(code)
    if not referrer:
        return False, None
    referrer_id = referrer.get("telegram_id")
    if referrer_id == new_user_id:
        return False, None  # сам себе реферал нельзя

    storage.set_referred_by(new_user_id, referrer_id)
    storage.extend_subscription_days(new_user_id, REFERRAL_BONUS_DAYS, target_plan="premium")
    storage.extend_subscription_days(referrer_id,  REFERRAL_BONUS_DAYS, target_plan="premium")
    storage.log_event(new_user_id, "referral_redeemed", {"referrer": referrer_id, "days": REFERRAL_BONUS_DAYS})
    storage.log_event(referrer_id, "referral_invited",  {"new_user": new_user_id, "days": REFERRAL_BONUS_DAYS})
    return True, referrer.get("first_name") or "друг"


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обрабатывает /start — регистрирует пользователя, обрабатывает реферал, показывает меню."""
    user = message.from_user
    first_name = user.first_name or "Друг"

    storage.get_or_create_user(
        telegram_id=user.id,
        username=user.username or "",
        first_name=first_name,
    )

    # Реферальный параметр /start ref_<code>
    referral_note = ""
    ref_param = _parse_start_param(message.text)
    if ref_param.startswith("ref_"):
        applied, referrer_name = await _apply_referral(user.id, ref_param)
        if applied:
            referral_note = (
                f"\n🎉 <b>Реферальный бонус активирован!</b>\n"
                f"Тебе и {referrer_name} начислено по {REFERRAL_BONUS_DAYS} дней Premium.\n"
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
        f"{webapp_note}"
        f"{referral_note}\n\n"
        "Просто напиши свою первую трату или нажми кнопку ниже 👇",
        reply_markup=get_main_menu(),
        parse_mode="HTML",
    )
