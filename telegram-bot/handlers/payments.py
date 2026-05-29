"""Платежи через Lava.top: создание подписки, отправка ссылки на оплату."""
import logging
import os

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from services import lava, plans, storage

logger = logging.getLogger(__name__)
router = Router()


def _admin_id() -> int | None:
    raw = os.getenv("ADMIN_ID") or os.getenv("OWNER_ID")
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


async def _start_lava_checkout(callback: CallbackQuery, tier: str) -> None:
    """Создаёт инвойс на подписку и отдаёт юзеру инлайн-кнопку с paymentUrl."""
    offer_id = plans.LAVA_OFFER_IDS.get(tier)
    price = plans.PRICE_USD.get(tier)
    title = plans.PLAN_TITLE.get(tier, tier)
    if not offer_id or not price:
        await callback.answer("План недоступен", show_alert=True)
        return

    storage.log_event(callback.from_user.id, "upgrade_clicked", {"tier": tier, "provider": "lava"})

    invoice = await lava.create_subscription(
        telegram_id=callback.from_user.id,
        offer_id=offer_id,
    )
    if not invoice or not invoice.get("paymentUrl"):
        await callback.answer(
            "Не удалось создать счёт. Попробуй ещё раз через минуту.",
            show_alert=True,
        )
        return

    payment_url = invoice["paymentUrl"]
    contract_id = invoice.get("id", "")

    storage.log_event(callback.from_user.id, "lava_invoice_created", {
        "tier": tier, "contract_id": contract_id, "amount_usd": price,
    })

    # Перед чекаутом показываем что входит в тариф — иначе юзер видит только
    # «оплати $5/мес» и не понимает за что платит.
    from handlers.plan import _build_tier_summary

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Оплатить ${price}/мес", url=payment_url)],
    ])
    await callback.message.answer(
        f"{_build_tier_summary(tier)}\n\n"
        f"Жми кнопку ниже, оплати картой — после оплаты бот сам активирует "
        f"подписку. Списание каждый месяц автоматически, можно отменить в "
        f"любой момент.\n\n"
        f"⏱ <i>Подтверждение придёт в течение 1 минуты после оплаты.</i>",
        parse_mode="HTML",
        reply_markup=kb,
    )
    await callback.answer("Открываю оплату…")


@router.callback_query(F.data == "upgrade_premium")
async def cb_upgrade_premium(callback: CallbackQuery):
    await _start_lava_checkout(callback, plans.PLAN_PREMIUM)


@router.callback_query(F.data == "upgrade_pro")
async def cb_upgrade_pro(callback: CallbackQuery):
    await _start_lava_checkout(callback, plans.PLAN_PRO)
