"""Команда /invite — реферальная программа."""
import logging
import os

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from services import storage

logger = logging.getLogger(__name__)
router = Router()

REFERRAL_BONUS_DAYS = 14


def _bot_username() -> str:
    return os.getenv("BOT_USERNAME", "smartcash_ai_bot")


def _ref_link(code: str) -> str:
    return f"https://t.me/{_bot_username()}?start=ref_{code}"


@router.message(Command("invite"))
async def cmd_invite(message: Message):
    """Показывает реферальную ссылку и счётчик приглашений."""
    user = storage.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала нажми /start.")
        return

    code = user.get("referral_code")
    if not code:
        await message.answer("Реф-код ещё не выдан. Напиши боту /start и попробуй ещё раз.")
        return

    link = _ref_link(code)

    # Счётчик приглашённых через events
    invited_count = storage.count_events_this_month(user.id, "referral_invited") if False else 0
    # Простое решение через прямой select — без новых helper'ов
    try:
        from services.storage import _client
        res = _client().table("events").select("id", count="exact") \
            .eq("telegram_id", message.from_user.id) \
            .eq("type", "referral_invited") \
            .execute()
        invited_count = res.count or 0
    except Exception as e:
        logger.warning(f"invite count: {e}")

    await message.answer(
        f"🎁 <b>Пригласи друга — получите по {REFERRAL_BONUS_DAYS} дней Premium</b>\n\n"
        f"Твоя ссылка:\n<code>{link}</code>\n\n"
        f"Когда друг откроет бота по твоей ссылке и сделает /start — обоим автоматически "
        f"начислится {REFERRAL_BONUS_DAYS} дней Premium-подписки.\n\n"
        f"👥 Приглашено: <b>{invited_count}</b>\n"
        f"🎉 Получено бонусных дней: <b>{invited_count * REFERRAL_BONUS_DAYS}</b>",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
