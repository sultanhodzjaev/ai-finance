"""Команда /invite — реферальная программа."""
import logging
import os

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from services import storage

logger = logging.getLogger(__name__)
router = Router()

REFERRAL_BONUS_DAYS = 7


def _bot_username() -> str:
    return os.getenv("BOT_USERNAME", "smartcash_ai_bot")


def _ref_link(code: str) -> str:
    return f"https://t.me/{_bot_username()}?start=ref_{code}"


def _invite_text(telegram_id: int) -> str | None:
    """Готовит текст приглашения. Возвращает None если юзер не найден или код не выдан."""
    user = storage.get_user(telegram_id)
    if not user:
        return None
    code = user.get("referral_code")
    if not code:
        # На случай если миграция/инсёрт оставили код пустым — генерим on-the-fly,
        # чтобы кнопка «Пригласить друга» не отдавала «Сначала нажми /start» по кругу.
        import hashlib, time as _time
        code = hashlib.md5(f"{telegram_id}{_time.time()}".encode()).hexdigest()[:8]
        try:
            from services.storage import _client
            _client().table("users").update({"referral_code": code}).eq("telegram_id", telegram_id).execute()
        except Exception as e:
            logger.warning(f"backfill referral_code({telegram_id}): {e}")
            return None

    link = _ref_link(code)
    try:
        from services.storage import _client
        res = _client().table("events").select("id", count="exact") \
            .eq("telegram_id", telegram_id) \
            .eq("type", "referral_invited") \
            .execute()
        invited_count = res.count or 0
    except Exception as e:
        logger.warning(f"invite count: {e}")
        invited_count = 0

    return (
        f"🎁 <b>Пригласи друга — получите по {REFERRAL_BONUS_DAYS} дней Premium</b>\n\n"
        f"Твоя ссылка:\n<code>{link}</code>\n\n"
        f"Когда друг откроет бота по твоей ссылке и сделает /start — обоим автоматически "
        f"начислится {REFERRAL_BONUS_DAYS} дней Premium-подписки.\n\n"
        f"👥 Приглашено: <b>{invited_count}</b>\n"
        f"🎉 Получено бонусных дней: <b>{invited_count * REFERRAL_BONUS_DAYS}</b>"
    )


@router.message(Command("invite"))
async def cmd_invite(message: Message):
    """Показывает реферальную ссылку и счётчик приглашений."""
    text = _invite_text(message.from_user.id)
    if not text:
        await message.answer("Сначала нажми /start, потом попробуй ещё раз.")
        return
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


@router.callback_query(F.data == "show_invite")
async def cb_show_invite(callback: CallbackQuery):
    """Кнопка «🎁 Пригласить друга» из главного меню."""
    text = _invite_text(callback.from_user.id)
    if not text:
        await callback.answer("Сначала нажми /start", show_alert=True)
        return
    await callback.message.answer(text, parse_mode="HTML", disable_web_page_preview=True)
    await callback.answer()
