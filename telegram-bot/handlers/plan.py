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


def _used_for(action: str, telegram_id: int) -> int:
    period = plans.period_for(action)
    if action == "transaction":
        return (
            storage.count_transactions_today(telegram_id, source="text")
            if period == "day"
            else storage.count_transactions_this_month(telegram_id, source="text")
        )
    if action == "photo":
        return (
            storage.count_transactions_today(telegram_id, source="photo")
            if period == "day"
            else storage.count_transactions_this_month(telegram_id, source="photo")
        )
    if action == "ai_question":
        return (
            storage.count_events_today(telegram_id, "ai_question")
            if period == "day"
            else storage.count_events_this_month(telegram_id, "ai_question")
        )
    if action == "voice":
        return (
            storage.count_events_today(telegram_id, "voice")
            if period == "day"
            else storage.count_events_this_month(telegram_id, "voice")
        )
    return 0


def _upgrade_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"💎 Premium — {plans.PRICE_STARS[plans.PLAN_PREMIUM]}⭐",
            callback_data="upgrade_premium",
        )],
        [InlineKeyboardButton(
            text=f"🚀 Pro — {plans.PRICE_STARS[plans.PLAN_PRO]}⭐",
            callback_data="upgrade_pro",
        )],
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

    # Когда что заканчивается
    if plan == plans.PLAN_TRIAL:
        time_left = _fmt_remaining(user.get("trial_until"))
        time_line = f"⏳ До конца триала: <b>{time_left}</b>"
    elif plan in (plans.PLAN_PREMIUM, plans.PLAN_PRO):
        if user.get("subscription_until"):
            time_left = _fmt_remaining(user.get("subscription_until"))
            time_line = f"⏳ Подписка до: <b>{time_left}</b>"
        else:
            time_line = "♾️ Подписка бессрочная"
    else:
        time_line = "📭 Бесплатный режим"

    def _line(name: str, action: str) -> str:
        lim = plans.limit_for(plan, action)
        period = plans.period_for(action)
        period_word = "сегодня" if period == "day" else "в этом месяце"
        if lim == 0:
            return f"  • {name}: ❌ недоступно"
        used = _used_for(action, user_id)
        return f"  • {name}: <b>{used}/{lim}</b> {period_word}"

    text = (
        f"📋 <b>Твой план: {title}</b>\n"
        f"{time_line}\n\n"
        f"<b>Лимиты:</b>\n"
        f"{_line('Записи трат', 'transaction')}\n"
        f"{_line('Фото чеков', 'photo')}\n"
        f"{_line('Вопросов финансисту', 'ai_question')}\n"
    )

    if plan in (plans.PLAN_FREE, plans.PLAN_TRIAL):
        text += "\nЧтобы снять ограничения — /upgrade"
    elif plan == plans.PLAN_PREMIUM:
        text += "\nХочешь больше лимитов? Pro — /upgrade"

    await message.answer(text, parse_mode="HTML")


@router.message(Command("upgrade"))
async def cmd_upgrade(message: Message):
    """Показывает варианты подписки. Сам платёж — следующий коммит."""
    storage.log_event(message.from_user.id, "upgrade_clicked", {"source": "command"})
    await message.answer(
        "💳 <b>Подписка AI-Финансист</b>\n\n"
        "💎 <b>Premium — 350⭐ ≈ $7 / мес</b>\n"
        "  • 17 трат / день (≈500/мес)\n"
        "  • 1 фото чек / день (≈30/мес)\n"
        "  • 300 вопросов финансисту / мес\n"
        "  • Голос: 60/мес\n"
        "  • История: 12 мес\n"
        "  • Импорт CSV и экспорт (3 в мес)\n\n"
        "🚀 <b>Pro — 750⭐ ≈ $15 / мес</b>\n"
        "  • 100 трат / день (≈3000/мес)\n"
        "  • 5 фото чеков / день (≈150/мес)\n"
        "  • 1500 вопросов финансисту / мес\n"
        "  • Голос: 200/мес\n"
        "  • История: 24 мес\n"
        "  • Экспорт (10 в мес), 100 категорий\n\n"
        "💫 Оплата — в Telegram Stars. Подписка на 30 дней.",
        parse_mode="HTML",
        reply_markup=_upgrade_keyboard(),
    )
