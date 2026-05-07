import io
import json
import logging
import os
import re

from google import genai
from google.genai import types
from PIL import Image

logger = logging.getLogger(__name__)

VALID_CATEGORIES = [
    "food", "groceries", "transport", "entertainment",
    "health", "clothes", "home", "communication", "gifts", "other"
]


def _get_client() -> genai.Client:
    """Создаёт и возвращает клиент Gemini."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY не найден в переменных окружения")
    return genai.Client(api_key=api_key)


def _extract_json(text: str) -> dict:
    """Извлекает JSON из ответа модели — убирает markdown-обёртку если есть."""
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    return json.loads(text.strip())


async def categorize_text_transaction(user_message: str) -> dict:
    """
    Отправляет текстовое сообщение в Gemini для категоризации как транзакции.
    Возвращает dict: {amount, category, description, success} или {success: False, reason}.
    """
    prompt = f"""Ты — AI-помощник для учёта личных финансов. Пользователь прислал сообщение о трате на русском языке.

Твоя задача — извлечь из сообщения сумму, категорию и описание.

Доступные категории (используй только эти id):
- food (Еда — рестораны, кафе, обеды вне дома)
- groceries (Продукты — покупки в магазинах для дома)
- transport (Транспорт — такси, бензин, проезд)
- entertainment (Развлечения — кино, концерты, бары)
- health (Здоровье — врачи, лекарства, спортзал)
- clothes (Одежда — одежда, обувь, аксессуары)
- home (Жильё — аренда, коммуналка, ремонт)
- communication (Связь — интернет, мобильная связь)
- gifts (Подарки — подарки, благотворительность)
- other (Другое — всё остальное)

Сообщение пользователя: "{user_message}"

Ответь СТРОГО в формате JSON, без пояснений и markdown:
{{
  "amount": число (сумма траты),
  "category": "id_категории",
  "description": "краткое описание (до 30 символов)",
  "success": true
}}

Если не можешь определить трату (например, пользователь поздоровался или задал вопрос):
{{
  "success": false,
  "reason": "не похоже на трату"
}}"""

    try:
        client = _get_client()
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        result = _extract_json(response.text)

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
    Отправляет фото чека в Gemini для распознавания.
    Возвращает dict: {amount, category, merchant, description, success} или {success: False, reason}.
    """
    prompt = """Ты — AI-помощник для распознавания чеков. На фото — чек о покупке.

Твоя задача — извлечь:
- Общую сумму чека
- Название магазина/заведения
- Категорию (по типу заведения)
- Краткое описание

Доступные категории (только эти id):
food, groceries, transport, entertainment, health, clothes, home, communication, gifts, other

Ответь СТРОГО в формате JSON:
{
  "amount": число,
  "category": "id_категории",
  "merchant": "название магазина",
  "description": "краткое описание чека",
  "success": true
}

Если на фото не чек или невозможно распознать:
{
  "success": false,
  "reason": "не удалось распознать чек"
}"""

    try:
        client = _get_client()
        image = Image.open(io.BytesIO(photo_bytes))

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                prompt,
                image,
            ],
        )
        result = _extract_json(response.text)

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
    transactions: list
) -> str:
    """
    Отправляет вопрос пользователя AI-финансисту вместе с контекстом его трат.
    Возвращает текстовый ответ финансиста.
    """
    from datetime import datetime, timedelta

    if transactions:
        transactions_list = "\n".join([
            f"- {t['datetime'][:10]}: {t.get('description', '—')} | "
            f"{t['amount']} {currency} | категория: {t['category']}"
            for t in transactions[-100:]
        ])
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
        categories_stats = "\n".join([
            f"- {cat}: {amount:.0f} {currency}"
            for cat, amount in sorted(categories_totals.items(), key=lambda x: -x[1])
        ])
    else:
        categories_stats = "Данных за последний месяц нет"

    prompt = f"""Ты — личный AI-финансист пользователя. Твоя роль — давать практичные, дружелюбные и полезные советы о финансах на русском языке.

Стиль общения:
- Тёплый и дружеский, на "ты"
- Без банковского официоза
- Конкретика, цифры, проценты
- Если уместно — добавь эмодзи (но не переборщи)
- Короткие абзацы

Данные пользователя:
- Валюта: {currency}
- Всего транзакций: {len(transactions)}

Все траты пользователя:
{transactions_list}

Статистика по категориям за последний месяц:
{categories_stats}

Вопрос пользователя: "{user_question}"

Дай развёрнутый ответ (3-7 предложений), который реально поможет пользователю. Если данных мало — честно скажи об этом. Если уместно — дай конкретный совет или рекомендацию."""

    try:
        client = _get_client()
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        return response.text.strip()
    except Exception as e:
        logger.error(f"Ошибка при запросе к AI-финансисту: {e}")
        raise
