"""Команды /plan и /upgrade — управление подпиской."""
import logging
from datetime import datetime, timezone

from aiogram import Router, F
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
            storage.count_transactions_today(telegram_id, source="voice")
            if period == "day"
            else storage.count_transactions_this_month(telegram_id, source="voice")
        )
    return 0


def _upgrade_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"💎 Premium — ${plans.PRICE_USD[plans.PLAN_PREMIUM]}/мес",
            callback_data="upgrade_premium",
        )],
        [InlineKeyboardButton(
            text=f"🚀 Pro — ${plans.PRICE_USD[plans.PLAN_PRO]}/мес",
            callback_data="upgrade_pro",
        )],
    ])


def build_plan_text(user_id: int) -> str | None:
    """Собирает текст /plan для юзера. None — если юзера нет в базе."""
    user = storage.get_user(user_id)
    if not user:
        return None

    plan = plans.effective_plan(user)
    title = plans.PLAN_TITLE.get(plan, plan)

    # Owner — allowlist-юзер с безлимитом, лимиты ему показывать бессмысленно.
    if plan == plans.PLAN_OWNER:
        return (
            f"👑 <b>Твой план: Owner</b>\n"
            f"♾️ Безлимитный доступ ко всем функциям бота.\n\n"
            f"Этот режим выдаётся вручную через allowlist (OWNER_TELEGRAM_IDS)."
        )

    if plan == plans.PLAN_TRIAL:
        time_line = f"⏳ До конца триала: <b>{_fmt_remaining(user.get('trial_until'))}</b>"
    elif plan in (plans.PLAN_PREMIUM, plans.PLAN_PRO):
        if user.get("subscription_until"):
            time_line = f"⏳ Подписка до: <b>{_fmt_remaining(user.get('subscription_until'))}</b>"
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
    return text


@router.message(Command("plan"))
async def cmd_plan(message: Message):
    """Показывает текущий план юзера и его лимиты."""
    text = build_plan_text(message.from_user.id)
    if text is None:
        await message.answer("Сначала нажми /start — я тебя ещё не вижу в базе.")
        return
    await message.answer(text, parse_mode="HTML")


def _build_tier_summary(plan: str) -> str:
    """Краткое описание тарифа, собранное из LIMITS — гарантированно совпадает с реальными лимитами."""
    cfg = plans.LIMITS[plan]
    title = plans.PLAN_TITLE[plan]
    price = plans.PRICE_USD[plan]
    icon = "💎" if plan == plans.PLAN_PREMIUM else "🚀"
    history_months = (cfg["history_days"] // 30) if cfg.get("history_days") else None
    history_line = f"вся за период подписки" if history_months is None else f"{history_months} мес"
    return (
        f"{icon} <b>{title} — ${price} / мес</b>\n"
        f"  • {cfg['transactions_per_day']} текстовых трат / день\n"
        f"  • {cfg['photo_per_month']} фото чеков / мес\n"
        f"  • {cfg['voice_per_month']} голосовых / мес\n"
        f"  • {cfg['ai_questions_per_month']} вопросов AI-финансисту / мес\n"
        f"  • История: {history_line}\n"
        f"  • {cfg['categories_max']} категорий, "
        f"{cfg['recurring_payments_max']} регулярных платежей\n"
        f"  • Импорт CSV: {'да' if cfg['csv_import'] else 'нет'}\n"
        f"  • Экспортов: {cfg.get('exports_per_month', 0)} / мес"
    )


@router.message(Command("upgrade"))
async def cmd_upgrade(message: Message):
    """Показывает варианты подписки. Тексты тарифов формируются из LIMITS."""
    storage.log_event(message.from_user.id, "upgrade_clicked", {"source": "command"})
    await message.answer(
        "💳 <b>Подписка AI-Финансист</b>\n\n"
        f"{_build_tier_summary(plans.PLAN_PREMIUM)}\n\n"
        f"{_build_tier_summary(plans.PLAN_PRO)}\n\n"
        "💳 Оплата картой через Lava.top. Подписка автопродлевается каждый месяц, можно отменить в любой момент.",
        parse_mode="HTML",
        reply_markup=_upgrade_keyboard(),
    )
