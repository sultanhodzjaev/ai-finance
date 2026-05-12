"""Команды /plan и /upgrade — управление подпиской."""
import logging
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from services import plans, storage

logger = logging.getLogger(__name__)
router = Router()


def _fmt_remaining(target_iso: str | None) -> str:
    if not target_iso:
        return "—"
    try:
        s = str(target_iso).replace("Z", "+00:00")
        target = datetime.fromisoformat(s)
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        delta = target - datetime.now(timezone.utc)
        secs = int(delta.total_seconds())
        if secs <= 0:
            return "истёк"
        if secs >= 86400:
            return f"{secs // 86400} дн."
        if secs >= 3600:
            return f"{secs // 3600} ч."
        return f"{max(1, secs // 60)} мин."
    except Exception:
        return "—"


def _upgrade_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💼 Базовый — {plans.PRICE_STARS[plans.PLAN_BASIC]}⭐", callback_data="upgrade_basic")],
        [InlineKeyboardButton(text=f"💎 Премиум — {plans.PRICE_STARS[plans.PLAN_PREMIUM]}⭐", callback_data="upgrade_premium")],
    ])


@router.message(Command("plan"))
async def cmd_plan(message: Message):
    """Показывает текущий план юзера и его лимиты."""
    user_id = message.from_user.id
    user = storage.get_user(user_id)
    if not user:
        await message.answer("Сначала нажми /start — я тебя ещё не вижу в базе.")
        return

    plan = plans.effective_plan(user)
    title = plans.PLAN_TITLE.get(plan, plan)
    limits = plans.LIMITS[plan]

    # Текущее использование
    used_tx    = storage.count_transactions_today(user_id, source="text")
    used_photo = storage.count_transactions_today(user_id, source="photo")
    used_ai    = storage.count_events_today(user_id, "ai_question")

    # Когда что заканчивается
    if plan == plans.PLAN_TRIAL:
        time_left = _fmt_remaining(user.get("trial_until"))
        time_line = f"⏳ До конца триала: <b>{time_left}</b>"
    elif plan in (plans.PLAN_BASIC, plans.PLAN_PREMIUM):
        if user.get("subscription_until"):
            time_left = _fmt_remaining(user.get("subscription_until"))
            time_line = f"⏳ Подписка до: <b>{time_left}</b>"
        else:
            time_line = "♾️ Подписка бессрочная"
    else:
        time_line = "📭 Бесплатный режим"

    def _line(name: str, used: int, lim: int) -> str:
        if lim == 0:
            return f"  • {name}: ❌ недоступно"
        return f"  • {name}: <b>{used}/{lim}</b> сегодня"

    text = (
        f"📋 <b>Твой план: {title}</b>\n"
        f"{time_line}\n\n"
        f"<b>Лимиты:</b>\n"
        f"{_line('Записи трат', used_tx, limits['transaction'])}\n"
        f"{_line('Фото чеков', used_photo, limits['photo'])}\n"
        f"{_line('Вопросов финансисту', used_ai, limits['ai_question'])}\n"
    )

    if plan in (plans.PLAN_FREE, plans.PLAN_TRIAL):
        text += "\nЧтобы снять ограничения — /upgrade"
    elif plan == plans.PLAN_BASIC:
        text += "\nХочешь AI-финансиста? Подними план — /upgrade"

    await message.answer(text, parse_mode="HTML")


@router.message(Command("upgrade"))
async def cmd_upgrade(message: Message):
    """Показывает варианты подписки. Сам платёж — следующий коммит."""
    storage.log_event(message.from_user.id, "upgrade_clicked", {"source": "command"})
    await message.answer(
        "💳 <b>Подписка AI-Финансист</b>\n\n"
        "💼 <b>Базовый — 100⭐ ≈ $2 / мес</b>\n"
        "  • до 100 трат в день\n"
        "  • до 5 фото чеков в день\n"
        "  • полная история\n"
        "  • <i>без AI-финансиста</i>\n\n"
        "💎 <b>Премиум — 250⭐ ≈ $5 / мес</b>\n"
        "  • до 200 трат в день\n"
        "  • до 30 фото в день\n"
        "  • <b>AI-финансист с памятью контекста</b>\n"
        "  • до 30 вопросов в день\n\n"
        "⚙️ Оплата в Telegram Stars подключается на днях — следи за обновлениями.",
        parse_mode="HTML",
        reply_markup=_upgrade_keyboard(),
    )
