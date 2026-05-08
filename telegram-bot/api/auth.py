import hashlib
import hmac
import json
import logging
import os
from urllib.parse import parse_qsl

logger = logging.getLogger(__name__)


def _bot_token() -> str:
    """Читаем токен каждый раз — на случай если переменная задана после старта."""
    return os.getenv("BOT_TOKEN", "").strip()


def validate_init_data(init_data: str) -> dict | None:
    """
    Валидирует initData от Telegram WebApp по HMAC-SHA256.
    Возвращает dict с данными пользователя или None если подпись невалидна.
    Документация: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    bot_token = _bot_token()
    if not init_data or not bot_token:
        logger.warning("validate_init_data: пустой init_data или BOT_TOKEN")
        return None

    try:
        # parse_qsl без strict_parsing — принимает любой валидный URL-query
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)

        if not received_hash:
            logger.warning("validate_init_data: нет поля hash")
            return None

        # data_check_string = отсортированные key=value через \n
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed.items())
        )

        # secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
        secret_key = hmac.new(
            b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256
        ).digest()

        # expected = HMAC_SHA256(key=secret_key, msg=data_check_string)
        expected_hash = hmac.new(
            secret_key, data_check_string.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected_hash, received_hash):
            logger.warning(
                "validate_init_data: хэш не совпадает. "
                f"expected={expected_hash[:12]}… received={received_hash[:12]}…"
            )
            return None

        user_str = parsed.get("user")
        if user_str:
            return json.loads(user_str)

        logger.warning("validate_init_data: нет поля user в initData")
        return None

    except Exception as e:
        logger.error(f"validate_init_data: ошибка — {e}")
        return None


def parse_init_data_user(init_data: str) -> dict | None:
    """
    Возвращает сырой dict пользователя из initData (без проверки хэша).
    Только для авто-регистрации — не использовать для авторизации!
    """
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        user_str = parsed.get("user")
        return json.loads(user_str) if user_str else None
    except Exception:
        return None


def get_telegram_id(init_data: str) -> int | None:
    """Извлекает telegram_id из валидированного initData."""
    user = validate_init_data(init_data)
    return user.get("id") if user else None
