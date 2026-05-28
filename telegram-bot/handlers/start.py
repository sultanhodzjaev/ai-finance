import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardRemove

from services import storage
from handlers.onboarding import currency_picker_kb, main_inline_kb

logger = logging.getLogger(__name__)
router = Router()

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
    """Обрабатывает /start — регистрирует пользователя, обрабатывает реферал, запускает онбординг."""
    user = message.from_user

    # Защита от Telegram-ботов
    if user.is_bot:
        logger.info(f"start: ignoring Telegram bot user_id={user.id} username=@{user.username}")
        return

    first_name = user.first_name or "Друг"

    _, is_new = storage.get_or_create_user_with_flag(
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

    if is_new:
        # Свежий юзер → приветствие + выбор валюты. Trial-интро отправится после выбора (в onboarding.cb_set_currency).
        await message.answer(
            f"👋 Привет, {first_name}!\n\n"
            "Я — твой AI-финансист. Веду учёт трат без таблиц: пишешь обычным сообщением — "
            "я разбираю сумму, категорию и сохраняю. Голос и фото чеков тоже понимаю.\n\n"
            f"{referral_note}"
            "<b>Сначала выбери основную валюту</b> — в ней будут считаться все траты 👇",
            parse_mode="HTML",
            reply_markup=currency_picker_kb(),
        )
        return

    # Возвращающийся юзер: приветствие шлём с ReplyKeyboardRemove(), чтобы стереть legacy
    # persistent-клавиатуру у юзеров прошлой версии; следующим сообщением — inline-меню.
    await message.answer(
        f"👋 С возвращением, {first_name}!\n\n"
        "Напиши трату обычным сообщением или выбери действие 👇"
        f"{referral_note}",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer("Меню 👇", reply_markup=main_inline_kb())
