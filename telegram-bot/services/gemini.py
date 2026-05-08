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

# Список моделей в порядке приоритета
GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-flash-latest",
]
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Допустимые id для каждого типа транзакции
VALID_EXPENSE_CATEGORIES = [
    "food", "groceries", "transport", "entertainment",
    "health", "clothes", "home", "communication", "gifts", "other",
]
VALID_INCOME_CATEGORIES = [
    "salary", "freelance", "business", "investment", "gift_income", "other_income",
]

# Оставляем для обратной совместимости
VALID_CATEGORIES = VALID_EXPENSE_CATEGORIES


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
    Перебирает модели; при 429 делает до 3 попыток с нарастающей задержкой.
    """
    payload = {"contents": contents}
    key = _api_key()
    last_error: Exception = RuntimeError("Нет доступных моделей")

    for model in GEMINI_MODELS:
        url = f"{GEMINI_API_BASE}/{model}:generateContent?key={key}"

        for attempt in range(retries):
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url, json=payload,
                    headers={"Content-Type": "application/json"},
                )

            if response.status_code == 404:
                logger.warning(f"Модель {model} недоступна (404), пробую следующую...")
                last_error = httpx.HTTPStatusError(
                    f"404 для {model}", request=response.request, response=response
                )
                break

            if response.status_code == 429:
                wait = 5 * (attempt + 1)
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
    Категоризирует текстовое сообщение как трату или доход через Gemini.
    Возвращает dict: {type, amount, category, description, success}.
    """
    prompt = (
        "Ты — AI-помощник для учёта личных финансов. "
        "Пользователь прислал сообщение о финансовой операции на русском языке.\n\n"
        "Твоя задача — определить тип операции, сумму, категорию и описание.\n\n"
        "ТИП ОПЕРАЦИИ:\n"
        '- "expense" — пользователь потратил деньги (купил, заплатил, потратил)\n'
        '- "income"  — пользователь получил деньги (зарплата, фриланс, продал, подарили, дивиденды)\n\n'
        "КАТЕГОРИИ РАСХОДОВ (для type=expense):\n"
        "- food (Еда — рестораны, кафе, обеды вне дома)\n"
        "- groceries (Продукты — покупки в магазинах для дома)\n"
        "- transport (Транспорт — такси, бензин, проезд)\n"
        "- entertainment (Развлечения — кино, концерты, бары)\n"
        "- health (Здоровье — врачи, лекарства, спортзал)\n"
        "- clothes (Одежда — одежда, обувь, аксессуары)\n"
        "- home (Жильё — аренда, коммуналка, ремонт)\n"
        "- communication (Связь — интернет, мобильная связь)\n"
        "- gifts (Подарки — подарки кому-то, благотворительность)\n"
        "- other (Другое — всё остальное)\n\n"
        "КАТЕГОРИИ ДОХОДОВ (для type=income):\n"
        "- salary (Зарплата — основная работа)\n"
        "- freelance (Фриланс — заказы, разовая работа)\n"
        "- business (Бизнес — доход от своего дела)\n"
        "- investment (Инвестиции — дивиденды, продажа активов, крипта)\n"
        "- gift_income (Подарок — подарили деньги)\n"
        "- other_income (Другое — всё остальное)\n\n"
        f'Сообщение пользователя: "{user_message}"\n\n'
        "Ответь СТРОГО в формате JSON, без пояснений и markdown:\n"
        '{"type": "expense", "amount": число, "category": "id_категории", "description": "краткое описание", "success": true}\n\n'
        "Если не можешь определить операцию:\n"
        '{"success": false, "reason": "не похоже на финансовую операцию"}'
    )

    try:
        text = await _generate([{"parts": [{"text": prompt}]}])
        result = _extract_json(text)

        if result.get("success"):
            tx_type = result.get("type", "expense")
            if tx_type == "income":
                result["type"] = "income"
                if result.get("category") not in VALID_INCOME_CATEGORIES:
                    result["category"] = "other_income"
            else:
                result["type"] = "expense"
                if result.get("category") not in VALID_EXPENSE_CATEGORIES:
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
    Распознаёт чек на фото через Gemini Vision. Чеки — всегда расходы.
    Возвращает dict: {amount, category, merchant, description, success}.
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

        if result.get("success"):
            # Чеки — всегда расходы
            result["type"] = "expense"
            if result.get("category") not in VALID_EXPENSE_CATEGORIES:
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
    Отправляет вопрос AI-финансисту с полным контекстом доходов и расходов.
    """
    from datetime import datetime, timedelta

    month_ago = datetime.now() - timedelta(days=30)

    # Разделяем транзакции за последний месяц на доходы и расходы
    income_by_cat: dict[str, float] = {}
    expense_by_cat: dict[str, float] = {}
    first_dt = last_dt = None

    for t in transactions:
        try:
            dt = datetime.fromisoformat(t["datetime"])
            first_dt = min(first_dt, dt) if first_dt else dt
            last_dt  = max(last_dt, dt)  if last_dt  else dt
            if dt >= month_ago:
                tx_type = t.get("type", "expense")
                cat = t.get("category", "other")
                if tx_type == "income":
                    income_by_cat[cat] = income_by_cat.get(cat, 0) + t["amount"]
                else:
                    expense_by_cat[cat] = expense_by_cat.get(cat, 0) + t["amount"]
        except Exception:
            pass

    total_income  = sum(income_by_cat.values())
    total_expense = sum(expense_by_cat.values())
    balance       = total_income - total_expense

    income_list = "\n".join(
        f"- {cat}: {amt:.0f} {currency}"
        for cat, amt in sorted(income_by_cat.items(), key=lambda x: -x[1])
    ) or "Доходов за последний месяц нет"

    expense_list = "\n".join(
        f"- {cat}: {amt:.0f} {currency}"
        for cat, amt in sorted(expense_by_cat.items(), key=lambda x: -x[1])
    ) or "Расходов за последний месяц нет"

    # Все транзакции (последние 100)
    if transactions:
        all_tx_lines = []
        for t in transactions[-100:]:
            sign = "+" if t.get("type") == "income" else "-"
            all_tx_lines.append(
                f"- {t['datetime'][:10]}: {sign}{t['amount']} {currency} | "
                f"{t.get('description', '—')} | {t.get('category', '?')}"
            )
        all_tx = "\n".join(all_tx_lines)
    else:
        all_tx = "Транзакций пока нет"

    first_date = first_dt.strftime("%d.%m.%Y") if first_dt else "нет данных"
    last_date  = last_dt.strftime("%d.%m.%Y")  if last_dt  else "нет данных"

    prompt = (
        "Ты — личный AI-финансист пользователя. "
        "Давай практичные, дружелюбные советы на русском языке. "
        "Стиль: тёплый, на 'ты', без официоза, конкретные цифры.\n\n"
        f"Валюта: {currency}\n"
        f"Период данных: с {first_date} по {last_date}\n\n"
        f"ДОХОДЫ за последний месяц:\n{income_list}\n"
        f"Итого доходов: {total_income:.0f} {currency}\n\n"
        f"РАСХОДЫ за последний месяц:\n{expense_list}\n"
        f"Итого расходов: {total_expense:.0f} {currency}\n\n"
        f"Остаток (доходы − расходы): {balance:+.0f} {currency}\n\n"
        f"Все транзакции:\n{all_tx}\n\n"
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
