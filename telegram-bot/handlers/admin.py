"""Админ-команды: /ban, /unban, /admin_stats. Только для владельца бота."""
import logging
import os

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from services import storage

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
