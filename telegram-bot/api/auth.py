import hashlib
import hmac
import json
import os
from urllib.parse import parse_qsl

BOT_TOKEN = os.getenv("BOT_TOKEN", "")


def validate_init_data(init_data: str) -> dict | None:
    """
    Валидирует initData от Telegram WebApp по HMAC-SHA256.
    Возвращает dict с данными пользователя или None если подпись невалидна.
    Документация: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    if not init_data or not BOT_TOKEN:
        return None
    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None

        # Строка для проверки — отсортированные пары key=value через \n
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed.items())
        )

        # secret_key = HMAC_SHA256(key="WebAppData", msg=BOT_TOKEN)
        secret_key = hmac.new(
            b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256
        ).digest()

        # Вычисляем ожидаемый хэш
        expected_hash = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected_hash, received_hash):
            return None

        # Извлекаем данные пользователя
        user_str = parsed.get("user")
        if user_str:
            return json.loads(user_str)
        return None

    except Exception:
        return None


def get_telegram_id(init_data: str) -> int | None:
    """Извлекает telegram_id из валидированного initData."""
    user = validate_init_data(init_data)
    return user.get("id") if user else None
