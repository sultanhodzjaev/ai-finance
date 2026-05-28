"""Админ-команды: /ban, /unban, /admin_stats, /setplan. Только для владельца бота."""
import logging
import os
from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from services import storage, plans

logger = logging.getLogger(__name__)
router = Router()


def _admin_id() -> int | None:
    raw = os.getenv("ADMIN_ID") or os.getenv("OWNER_ID")
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


def _is_admin(message: Message) -> bool:
    admin = _admin_id()
    return admin is not None and message.from_user.id == admin


@router.message(Command("ban"))
async def cmd_ban(message: Message):
    """/ban <telegram_id> [reason]"""
    if not _is_admin(message):
        return
    args = (message.text or "").split(maxsplit=2)
    if len(args) < 2:
        await message.answer("Формат: <code>/ban &lt;id&gt; [причина]</code>", parse_mode="HTML")
        return
    try:
        uid = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return
    reason = args[2] if len(args) > 2 else ""
    if storage.ban_user(uid, reason=reason, banned_by=message.from_user.id):
        await message.answer(f"Юзер <code>{uid}</code> забанен. Причина: {reason or '—'}", parse_mode="HTML")
    else:
        await message.answer("Не удалось забанить.")


@router.message(Command("unban"))
async def cmd_unban(message: Message):
    if not _is_admin(message):
        return
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Формат: <code>/unban &lt;id&gt;</code>", parse_mode="HTML")
        return
    try:
        uid = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return
    if storage.unban_user(uid):
        await message.answer(f"Юзер <code>{uid}</code> разбанен.", parse_mode="HTML")
    else:
        await message.answer("Такого юзера в бан-списке не было.")


@router.message(Command("setplan"))
async def cmd_setplan(message: Message):
    """Сменить план себе или другому юзеру.
    Формат: /setplan <plan> [days] [user_id]
      plan: trial | free | premium | pro
      days: сколько дней действует (для trial → trial_until; для premium/pro → subscription_until). По умолчанию 7.
      user_id: если не указан — себе.
    Примеры:
      /setplan trial          — Trial на 7 дней себе
      /setplan free           — Free сразу (no expiry)
      /setplan premium 30     — Premium на 30 дней себе
      /setplan pro 7 12345    — Pro на 7 дней для юзера 12345
    """
    if not _is_admin(message):
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer(
            "Формат: <code>/setplan &lt;trial|free|premium|pro&gt; [days] [user_id]</code>",
            parse_mode="HTML",
        )
        return

    plan = parts[1].lower()
    allowed_plans = {plans.PLAN_TRIAL, plans.PLAN_FREE, plans.PLAN_PREMIUM, plans.PLAN_PRO}
    if plan not in allowed_plans:
        await message.answer(f"План должен быть один из: {', '.join(sorted(allowed_plans))}.")
        return

    try:
        days = int(parts[2]) if len(parts) >= 3 else 7
    except ValueError:
        await message.answer("days должно быть числом.")
        return

    try:
        target_uid = int(parts[3]) if len(parts) >= 4 else message.from_user.id
    except ValueError:
        await message.answer("user_id должен быть числом.")
        return

    until = datetime.now(timezone.utc) + timedelta(days=days)
    if plan == plans.PLAN_TRIAL:
        storage.update_user_plan(target_uid, plan, trial_until=until)
        status = f"Trial до {until.strftime('%Y-%m-%d %H:%M UTC')}"
    elif plan == plans.PLAN_FREE:
        storage.update_user_plan(target_uid, plan)
        status = "Free (без срока)"
    else:
        storage.update_user_plan(target_uid, plan, subscription_until=until)
        status = f"{plans.PLAN_TITLE.get(plan, plan)} до {until.strftime('%Y-%m-%d %H:%M UTC')}"

    # Если меняем СЕБЕ и сейчас сидим в Owner-allowlist — напомним что для теста
    # надо ещё указать OWNER_DISABLED_TELEGRAM_IDS в env, иначе всё перекроется.
    note = ""
    if (target_uid == message.from_user.id and
            target_uid in plans.OWNER_TELEGRAM_IDS and
            target_uid not in plans._OWNER_DISABLED_TELEGRAM_IDS):
        note = (
            "\n\n⚠️ Ты сейчас в OWNER-allowlist — effective_plan всё равно вернёт Owner.\n"
            "Чтобы тестировать как обычный юзер, добавь в .env:\n"
            f"<code>OWNER_DISABLED_TELEGRAM_IDS={target_uid}</code>\n"
            "и перезапусти бота."
        )

    await message.answer(
        f"✅ План для <code>{target_uid}</code>: <b>{status}</b>{note}",
        parse_mode="HTML",
    )


@router.message(Command("admin_stats"))
async def cmd_admin_stats(message: Message):
    if not _is_admin(message):
        return
    s = storage.admin_stats()
    if not s:
        await message.answer("Не удалось получить статистику. Смотри логи сервера.")
        return
    plans_line = ", ".join(f"{p}: {n}" for p, n in sorted(s["users_by_plan"].items()))
    await message.answer(
        f"📊 <b>Сводка</b>\n\n"
        f"<b>Юзеры</b>\n"
        f"• Всего: <b>{s['users_total']}</b>\n"
        f"• За неделю: <b>{s['users_week']}</b>\n"
        f"• По планам: {plans_line or '—'}\n\n"
        f"<b>Транзакции</b>\n"
        f"• Всего: <b>{s['tx_total']}</b>\n"
        f"• За сегодня: <b>{s['tx_today']}</b>\n"
        f"• За неделю: <b>{s['tx_week']}</b>\n\n"
        f"<b>Активность</b>\n"
        f"• AI-вопросов сегодня: <b>{s['ai_today']}</b>\n"
        f"• Limit-hit'ов сегодня: <b>{s['limit_today']}</b>\n"
        f"• Платных подписок (всего): <b>{s['paid_total']}</b>",
        parse_mode="HTML",
    )
