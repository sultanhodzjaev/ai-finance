"""Клиент Lava.top: создание подписки и валидация webhook."""
from __future__ import annotations

import hmac
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

LAVA_BASE_URL = "https://gate.lava.top"
SYNTHETIC_EMAIL_DOMAIN = "botfinance.xyz"


def _api_key() -> str:
    return os.getenv("LAVA_API_KEY", "")


def _webhook_secret() -> str:
    return os.getenv("LAVA_WEBHOOK_SECRET", "")


def synthetic_email(telegram_id: int) -> str:
    return f"tg-{telegram_id}@{SYNTHETIC_EMAIL_DOMAIN}"


def parse_telegram_id_from_email(email: str) -> int | None:
    """Парсит telegram_id из синтетического email вида tg-<id>@botfinance.xyz."""
    if not email or "@" not in email:
        return None
    local, domain = email.split("@", 1)
    if domain.lower() != SYNTHETIC_EMAIL_DOMAIN:
        return None
    if not local.startswith("tg-"):
        return None
    try:
        return int(local[3:])
    except ValueError:
        return None


def verify_webhook_signature(received_key: str) -> bool:
    """Проверяет X-Api-Key, который Лава шлёт в webhook'е. hmac.compare_digest для защиты от timing-атак."""
    secret = _webhook_secret()
    if not secret or not received_key:
        return False
    return hmac.compare_digest(received_key, secret)


async def list_recent_invoices(size: int = 50) -> list[dict[str, Any]]:
    """Возвращает последние N инвойсов из Lava (по убыванию даты создания).
    Используется polling-таской — Lava webhook'и для Public API не доставляются
    надёжно (это известный баг, подтверждён на flowo-academy)."""
    api_key = _api_key()
    if not api_key:
        logger.error("list_recent_invoices: LAVA_API_KEY не задан")
        return []
    headers = {"X-Api-Key": api_key, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{LAVA_BASE_URL}/api/v2/invoices?size={int(size)}", headers=headers)
        if not r.is_success:
            logger.warning("lava list_recent_invoices: HTTP %s — %s", r.status_code, r.text[:300])
            return []
        data = r.json()
        return list(data.get("items") or [])
    except Exception as e:
        logger.exception("lava list_recent_invoices failed: %s", e)
        return []


async def create_subscription(
    *,
    telegram_id: int,
    offer_id: str,
    currency: str = "USD",
) -> dict[str, Any] | None:
    """Создаёт подписку через POST /api/v3/invoice. Возвращает {paymentUrl, contractId, ...} или None при ошибке."""
    api_key = _api_key()
    if not api_key:
        logger.error("create_subscription: LAVA_API_KEY не задан")
        return None

    body = {
        "email": synthetic_email(telegram_id),
        "offerId": offer_id,
        "currency": currency,
        "periodicity": "MONTHLY",
        "clientUtm": {
            "utm_source": "telegram_bot",
            "utm_campaign": f"tg_{telegram_id}",
        },
    }
    headers = {
        "X-Api-Key": api_key,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(f"{LAVA_BASE_URL}/api/v3/invoice", headers=headers, json=body)
        if r.status_code != 201:
            logger.error("lava create_subscription: HTTP %s — %s", r.status_code, r.text[:300])
            return None
        return r.json()
    except Exception as e:
        logger.exception("lava create_subscription failed: %s", e)
        return None
