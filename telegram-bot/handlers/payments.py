"""Telegram Stars-платежи: pre_checkout, successful_payment, активация подписки."""
import logging

from aiogram import Bot, Router, F
from aiogram.types import (
    Message, CallbackQuery, PreCheckoutQuery, LabeledPrice,
)

from services import plans, storage

logger = logging.getLogger(__name__)
router = Router()

# Сколько дней даёт одна покупка
SUBSCRIPTION_DAYS = 30


def _payload_for(tier: str, user_id: int) -> str:
    return f"{tier}:{user_id}"


def _parse_payload(payload: str) -> tuple[str | None, int | None]:
    try:
        tier, uid = payload.split(":", 1)
        return tier, int(uid)
    except Exception:
        return None, None


async def _send_invoice(bot: Bot, chat_id: int, tier: str) -> bool:
    """Отправляет Stars-инвойс в чат через sendInvoice. Возвращает True если успешно."""
    if tier == plans.PLAN_PREMIUM:
        title = "AI-Финансист — Premium"
        description = (
            "💎 Premium на 30 дней\n"
            "• 17 трат / день, 30 фото и 300 вопросов AI в месяц\n"
            "• Голос 60/мес, история 12 месяцев\n"
            "• Импорт CSV и экспорт"
        )
    elif tier == plans.PLAN_PRO:
        title = "AI-Финансист — Pro"
        description = (
            "🚀 Pro на 30 дней\n"
            "• 100 трат / день, 150 фото и 1500 вопросов AI в месяц\n"
            "• Голос 200/мес, история 24 месяца\n"
            "• Экспорт 10/мес, 100 категорий"
        )
    else:
        return False

    stars = plans.PRICE_STARS.get(tier)
    if not stars:
        return False

    try:
        await bot.send_invoice(
            chat_id=chat_id,
            title=title,
            description=description,
            payload=_payload_for(tier, chat_id),
            provider_token="",      # для Stars провайдер-токен пустой
            currency="XTR",         # XTR = Telegram Stars
            prices=[LabeledPrice(label=title, amount=stars)],
        )
        return True
    except Exception as e:
        logger.error(f"send_invoice({chat_id}, {tier}): {e}")
        return False


# ---------------------------------------------------------------------------
# Кнопки /upgrade — отправляют инвойс
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "upgrade_premium")
async def cb_upgrade_premium(callback: CallbackQuery):
    storage.log_event(callback.from_user.id, "upgrade_clicked", {"tier": plans.PLAN_PREMIUM})
    ok = await _send_invoice(callback.bot, callback.from_user.id, plans.PLAN_PREMIUM)
    await callback.answer("Открываю оплату…" if ok else "Не удалось создать счёт, попробуй позже",
                          show_alert=not ok)


@router.callback_query(F.data == "upgrade_pro")
async def cb_upgrade_pro(callback: CallbackQuery):
    storage.log_event(callback.from_user.id, "upgrade_clicked", {"tier": plans.PLAN_PRO})
    ok = await _send_invoice(callback.bot, callback.from_user.id, plans.PLAN_PRO)
    await callback.answer("Открываю оплату…" if ok else "Не удалось создать счёт, попробуй позже",
                          show_alert=not ok)


# ---------------------------------------------------------------------------
# Pre-checkout: Telegram спрашивает «можем продать?» — отвечаем «да»
# ---------------------------------------------------------------------------

@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery):
    tier, uid = _parse_payload(query.invoice_payload)
    if tier not in (plans.PLAN_PREMIUM, plans.PLAN_PRO) or not uid:
        await query.answer(ok=False, error_message="Внутренняя ошибка платежа")
        logger.warning(f"pre_checkout: bad payload {query.invoice_payload!r}")
        return
    await query.answer(ok=True)


# ---------------------------------------------------------------------------
# Successful payment: активируем подписку
# ---------------------------------------------------------------------------

@router.message(F.successful_payment)
async def on_successful_payment(message: Message):
    sp = message.successful_payment
    tier, uid = _parse_payload(sp.invoice_payload)
    if tier not in (plans.PLAN_PREMIUM, plans.PLAN_PRO) or not uid:
        logger.error(f"successful_payment: bad payload {sp.invoice_payload!r}")
        await message.answer("Платёж принят, но возникла ошибка при активации. Напиши в поддержку.")
        return

    # Защита от чужих платежей (вдруг payload подменили)
    if uid != message.from_user.id:
        logger.warning(f"successful_payment: payload uid {uid} != sender {message.from_user.id}")
        uid = message.from_user.id

    user = storage.activate_subscription(uid, tier, days=SUBSCRIPTION_DAYS)
    plan_title = plans.PLAN_TITLE.get(tier, tier)

    if not user:
        await message.answer(
            f"✅ Платёж получен ({sp.total_amount}⭐).\n"
            f"Но не удалось активировать {plan_title} автоматически. "
            f"Напиши /upgrade — ответим вручную."
        )
        return

    await message.answer(
        f"🎉 <b>Подписка {plan_title} активирована!</b>\n\n"
        f"Списано: {sp.total_amount}⭐\n"
        f"Срок: 30 дней\n\n"
        f"Все новые лимиты доступны прямо сейчас. Открой /plan чтобы посмотреть.",
        parse_mode="HTML",
    )
