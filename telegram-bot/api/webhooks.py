"""Внешние webhook'и (без префикса /miniapp/api). Сейчас только Lava.top."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from services import lava, plans, storage

logger = logging.getLogger(__name__)
router = APIRouter()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


async def _notify(bot, telegram_id: int, text: str) -> None:
    """Шлёт пушовое сообщение юзеру. Падения не пробрасываем — webhook должен ответить 2xx."""
    if bot is None:
        return
    try:
        await bot.send_message(telegram_id, text, parse_mode="HTML")
    except Exception as e:
        logger.warning("lava webhook notify(%s) failed: %s", telegram_id, e)


@router.post("/webhook/lava")
async def lava_webhook(request: Request) -> JSONResponse:
    """
    Принимает события Lava.top:
      - payment.success / status=subscription-active        → активация первой подписки
      - subscription.recurring.payment.success              → продление (+30 дней)
      - subscription.cancelled                              → не списываем больше, дать дожить до willExpireAt
      - payment.failed / subscription.recurring.*.failed    → лог
    """
    api_key = request.headers.get("x-api-key", "")
    if not lava.verify_webhook_signature(api_key):
        logger.warning("lava webhook: invalid X-Api-Key")
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        body: dict[str, Any] = await request.json()
    except Exception as e:
        logger.warning("lava webhook: bad json (%s)", e)
        return JSONResponse({"error": "bad_request"}, status_code=400)

    event = body.get("eventType", "")
    contract_id = body.get("contractId")
    buyer = body.get("buyer") or {}
    email = (buyer.get("email") or "").strip()
    amount = body.get("amount") or 0
    status = body.get("status", "")

    telegram_id = lava.parse_telegram_id_from_email(email)
    if not telegram_id:
        logger.warning("lava webhook %s: cannot parse telegram_id from email=%r contract=%s",
                       event, email, contract_id)
        return JSONResponse({"ok": True}, status_code=200)

    try:
        amount_int = int(round(float(amount)))
    except (TypeError, ValueError):
        amount_int = 0
    tier = plans.USD_TO_PLAN.get(amount_int)

    bot = getattr(request.app.state, "bot", None)

    storage.log_event(telegram_id, "lava_webhook", {
        "event": event, "status": status, "amount": amount,
        "currency": body.get("currency"), "contract_id": contract_id,
        "parent_contract_id": body.get("parentContractId"),
    })

    if event == "payment.success" and status == "subscription-active":
        if not tier:
            logger.warning("lava webhook payment.success: unknown tier for amount=%s tg=%s", amount, telegram_id)
            return JSONResponse({"ok": True})
        storage.activate_subscription(telegram_id, tier, days=30)
        title = plans.PLAN_TITLE.get(tier, tier)
        await _notify(bot, telegram_id,
                      f"🎉 <b>Подписка {title} активирована!</b>\n\n"
                      f"Списано: ${amount_int}/мес\n"
                      f"Следующее списание через 30 дней.\n\n"
                      f"Лимиты обновлены — открой /plan чтобы посмотреть.")
        return JSONResponse({"ok": True})

    if event == "subscription.recurring.payment.success" and status == "subscription-active":
        if not tier:
            logger.warning("lava webhook recurring: unknown tier for amount=%s tg=%s", amount, telegram_id)
            return JSONResponse({"ok": True})
        storage.activate_subscription(telegram_id, tier, days=30)
        title = plans.PLAN_TITLE.get(tier, tier)
        await _notify(bot, telegram_id,
                      f"🔄 <b>Подписка {title} продлена на 30 дней.</b>\n"
                      f"Списано: ${amount_int}.")
        return JSONResponse({"ok": True})

    if event == "subscription.cancelled":
        will_expire = _parse_iso(body.get("willExpireAt"))
        if will_expire and tier:
            storage.update_user_plan(telegram_id, tier, subscription_until=will_expire)
        await _notify(bot, telegram_id,
                      "🚫 Подписка отменена. Доступ сохраняется до конца оплаченного периода.\n"
                      "Возобновить — /upgrade")
        return JSONResponse({"ok": True})

    if event in ("payment.failed", "subscription.recurring.payment.failed"):
        await _notify(bot, telegram_id,
                      "⚠️ Платёж не прошёл. Возможно, на карте недостаточно средств "
                      "или банк отклонил списание. Попробуй ещё раз: /upgrade")
        return JSONResponse({"ok": True})

    logger.info("lava webhook unhandled: event=%s status=%s tg=%s", event, status, telegram_id)
    return JSONResponse({"ok": True})
