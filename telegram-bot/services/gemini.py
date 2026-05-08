import asyncio
import base64
import io
import json
import logging
import os
import re

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

# Список моделей в порядке приоритета — пробуем по очереди если предыдущая недоступна
GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-flash-latest",
]
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

VALID_CATEGORIES = [
    "food", "groceries", "transport", "entertainment",
    "health", "clothes", "home", "communication", "gifts", "other"
]

# Исключение для превышения лимита запросов — обрабатывается отдельно в хендлерах
class RateLimitError(Exception):
    pass


def _api_key() -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY не найден в переменных окружения")
    return key


async def _generate(contents: list, retries: int = 3) -> str:
    """
    Отправляет запрос к Gemini REST API и возвращает текст ответа.
    Перебирает модели по списку (gemini-2.0-flash → gemini-1.5-flash).
    При ошибке 429 делает до 3 попыток с нарастающей задержкой.
    """
    payload = {"contents": contents}
    key = _api_key()

    last_error: Exception = RuntimeError("Нет доступных моделей")

    for model in GEMINI_MODELS:
        url = f"{GEMINI_API_BASE}/{model}:generateContent?key={key}"

        for attempt in range(retries):
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )

            if response.status_code == 404:
                # Модель недоступна для этого ключа — пробуем следующую
                logger.warning(f"Модель {model} недоступна (404), пробую следующую...")
                last_error = httpx.HTTPStatusError(
                    f"404 для {model}", request=response.request, response=response
                )
                break  # выходим из retry-цикла, переходим к след. модели

            if response.status_code == 429:
                wait = 5 * (attempt + 1)  # 5с, 10с, 15с
                logger.warning(f"Rate limit 429 для {model}, попытка {attempt + 1}/{retries}, жду {wait}с...")
                if attempt < retries - 1:
                    await asyncio.sleep(wait)
                    continue
                else:
                    raise RateLimitError("Превышен лимит запросов к Gemini API")

            response.raise_for_status()
            data = response.json()
            logger.info(f"Используется модель: {model}")
            return data["candidates"][0]["content"]["parts"][0]["text"]

    raise last_error


def _extract_json(text: str) -> dict:
    """Извлекает JSON из ответа — убирает markdown-обёртку если есть."""
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    return json.loads(text.strip())


async def categorize_text_transaction(user_message: str) -> dict:
    """
    Категоризирует текстовое сообщение пользователя как трату через Gemini.
    Возвращает dict: {amount, category, description, success} или {success: False}.
    """
    prompt = (
        "Ты — AI-помощник для учёта личных финансов. "
        "Пользователь прислал сообщение о трате на русском языке.\n\n"
        "Твоя задача — извлечь из сообщения сумму, категорию и описание.\n\n"
        "Доступные категории (используй только эти id):\n"
        "- food (Еда — рестораны, кафе, обеды вне дома)\n"
        "- groceries (Продукты — покупки в магазинах для дома)\n"
        "- transport (Транспорт — такси, бензин, проезд)\n"
        "- entertainment (Развлечения — кино, концерты, бары)\n"
        "- health (Здоровье — врачи, лекарства, спортзал)\n"
        "- clothes (Одежда — одежда, обувь, аксессуары)\n"
        "- home (Жильё — аренда, коммуналка, ремонт)\n"
        "- communication (Связь — интернет, мобильная связь)\n"
        "- gifts (Подарки — подарки, благотворительность)\n"
        "- other (Другое — всё остальное)\n\n"
        f'Сообщение пользователя: "{user_message}"\n\n'
        "Ответь СТРОГО в формате JSON, без пояснений и markdown:\n"
        '{"amount": число, "category": "id_категории", "description": "краткое описание", "success": true}\n\n'
        "Если не можешь определить трату (пользователь поздоровался или задал вопрос):\n"
        '{"success": false, "reason": "не похоже на трату"}'
    )

    try:
        text = await _generate([{"parts": [{"text": prompt}]}])
        result = _extract_json(text)

        if result.get("success"):
            if result.get("category") not in VALID_CATEGORIES:
                result["category"] = "other"
            if not isinstance(result.get("amount"), (int, float)):
                return {"success": False, "reason": "невалидная сумма"}

        return result

    except json.JSONDecodeError as e:
        logger.error(f"Ошибка парсинга JSON от Gemini: {e}")
        return {"success": False, "reason": "ошибка парсинга ответа"}
    except Exception as e:
        logger.error(f"Ошибка при запросе к Gemini API: {e}")
        raise


async def recognize_receipt_photo(photo_bytes: bytes) -> dict:
    """
    Распознаёт чек на фото через Gemini Vision (multimodal).
    Возвращает dict: {amount, category, merchant, description, success} или {success: False}.
    """
    prompt = (
        "Ты — AI-помощник для распознавания чеков. На фото — чек о покупке.\n\n"
        "Извлеки: общую сумму, название магазина/заведения, категорию, краткое описание.\n\n"
        "Доступные категории (только эти id):\n"
        "food, groceries, transport, entertainment, health, clothes, home, communication, gifts, other\n\n"
        "Ответь СТРОГО в формате JSON:\n"
        '{"amount": число, "category": "id", "merchant": "название", "description": "описание", "success": true}\n\n'
        "Если на фото не чек или невозможно распознать:\n"
        '{"success": false, "reason": "не удалось распознать чек"}'
    )

    try:
        # Конвертируем фото в JPEG и кодируем в base64
        image = Image.open(io.BytesIO(photo_bytes))
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="JPEG")
        image_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        contents = [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
            ]
        }]

        text = await _generate(contents)
        result = _extract_json(text)

        if result.get("success") and result.get("category") not in VALID_CATEGORIES:
            result["category"] = "other"

        return result

    except json.JSONDecodeError as e:
        logger.error(f"Ошибка парсинга JSON от Gemini Vision: {e}")
        return {"success": False, "reason": "ошибка парсинга ответа"}
    except Exception as e:
        logger.error(f"Ошибка при запросе к Gemini Vision API: {e}")
        raise


async def ask_financial_advisor(
    user_question: str,
    currency: str,
    transactions: list,
) -> str:
    """
    Отправляет вопрос пользователя AI-финансисту с контекстом его трат.
    Возвращает текстовый ответ.
    """
    from datetime import datetime, timedelta

    if transactions:
        lines = []
        for t in transactions[-100:]:
            lines.append(
                f"- {t['datetime'][:10]}: {t.get('description', '—')} | "
                f"{t['amount']} {currency} | категория: {t['category']}"
            )
        transactions_list = "\n".join(lines)
    else:
        transactions_list = "Транзакций пока нет"

    month_ago = datetime.now() - timedelta(days=30)
    categories_totals: dict[str, float] = {}
    for t in transactions:
        try:
            dt = datetime.fromisoformat(t["datetime"])
            if dt >= month_ago:
                cat = t["category"]
                categories_totals[cat] = categories_totals.get(cat, 0) + t["amount"]
        except Exception:
            pass

    if categories_totals:
        cat_lines = [
            f"- {cat}: {amount:.0f} {currency}"
            for cat, amount in sorted(categories_totals.items(), key=lambda x: -x[1])
        ]
        categories_stats = "\n".join(cat_lines)
    else:
        categories_stats = "Данных за последний месяц нет"

    prompt = (
        "Ты — личный AI-финансист пользователя. "
        "Давай практичные, дружелюбные советы о финансах на русском языке. "
        "Стиль: теплый, на 'ты', без официоза, с конкретными цифрами.\n\n"
        f"Валюта пользователя: {currency}\n"
        f"Всего транзакций: {len(transactions)}\n\n"
        f"Все траты:\n{transactions_list}\n\n"
        f"Статистика по категориям за последний месяц:\n{categories_stats}\n\n"
        f'Вопрос пользователя: "{user_question}"\n\n'
        "Дай развёрнутый ответ (3-7 предложений). "
        "Если данных мало — честно скажи об этом. "
        "Если уместно — дай конкретный совет."
    )

    try:
        return await _generate([{"parts": [{"text": prompt}]}])
    except Exception as e:
        logger.error(f"Ошибка при запросе к AI-финансисту: {e}")
        raise
