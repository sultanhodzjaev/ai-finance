import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Query

from api.auth import get_telegram_id, validate_init_data, parse_init_data_user
from services.storage import (
    get_user, get_or_create_user, get_transactions, get_transaction,
    update_transaction, delete_transaction, add_transaction,
)
from utils.categories import CATEGORIES, INCOME_CATEGORIES

router = APIRouter(prefix="/miniapp/api")


def require_auth(init_data: str) -> int:
    telegram_id = get_telegram_id(init_data)
    if not telegram_id:
        raise HTTPException(status_code=401, detail="Invalid initData")
    return telegram_id


def ensure_user(init_data: str, telegram_id: int) -> dict:
    """
    Возвращает пользователя, авто-создавая его если он открыл Mini App
    до команды /start в боте.
    """
    user = get_user(telegram_id)
    if not user:
        # Берём имя из initData без проверки хэша (только для регистрации)
        tg_user = parse_init_data_user(init_data) or {}
        user = get_or_create_user(
            telegram_id=telegram_id,
            username=tg_user.get("username", ""),
            first_name=tg_user.get("first_name", "Друг"),
        )
    return user


@router.get("/me")
async def get_me(x_init_data: str = Header(...)):
    """Данные текущего пользователя. Авто-создаёт пользователя если нужно."""
    telegram_id = require_auth(x_init_data)
    user = ensure_user(x_init_data, telegram_id)
    return {
        "telegram_id": user["telegram_id"],
        "first_name":  user["first_name"],
        "currency":    user["currency"],
    }


@router.get("/transactions")
async def list_transactions(
    x_init_data: str = Header(...),
    type: Optional[str] = Query(None, description="Фильтр: income, expense или не указан"),
):
    """Все транзакции пользователя с опциональным фильтром по типу."""
    telegram_id = require_auth(x_init_data)
    ensure_user(x_init_data, telegram_id)
    txs = get_transactions(telegram_id)

    if type in ("income", "expense"):
        txs = [tx for tx in txs if tx.get("type", "expense") == type]

    return {"transactions": sorted(txs, key=lambda t: t["datetime"], reverse=True)}


@router.post("/transactions")
async def create_transaction(payload: dict, x_init_data: str = Header(...)):
    """Создать транзакцию из Mini App (без AI)."""
    telegram_id = require_auth(x_init_data)
    ensure_user(x_init_data, telegram_id)
    tx = {
        "id":          str(uuid.uuid4()),
        "type":        payload.get("type", "expense"),
        "amount":      float(payload["amount"]),
        "category":    payload.get("category", "other"),
        "description": payload.get("description", ""),
        "merchant":    None,
        "datetime":    datetime.now().isoformat(),
        "source":      "miniapp",
    }
    add_transaction(telegram_id, tx)
    return tx


@router.patch("/transactions/{tx_id}")
async def edit_transaction(tx_id: str, payload: dict, x_init_data: str = Header(...)):
    """Обновить сумму, категорию или описание транзакции."""
    telegram_id = require_auth(x_init_data)
    allowed = {"amount", "category", "description", "type"}
    updates = {k: v for k, v in payload.items() if k in allowed}
    if "amount" in updates:
        updates["amount"] = float(updates["amount"])
    tx = update_transaction(telegram_id, tx_id, updates)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return tx


@router.delete("/transactions/{tx_id}")
async def remove_transaction(tx_id: str, x_init_data: str = Header(...)):
    """Удалить транзакцию."""
    telegram_id = require_auth(x_init_data)
    ok = delete_transaction(telegram_id, tx_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {"success": True}


@router.get("/stats")
async def get_stats(x_init_data: str = Header(...)):
    """Статистика доходов и расходов за текущий месяц."""
    telegram_id = require_auth(x_init_data)
    txs = get_transactions(telegram_id)
    now = datetime.now()

    month_txs = [
        t for t in txs
        if datetime.fromisoformat(t["datetime"]).month == now.month
        and datetime.fromisoformat(t["datetime"]).year  == now.year
    ]

    expenses = [t for t in month_txs if t.get("type", "expense") == "expense"]
    incomes  = [t for t in month_txs if t.get("type") == "income"]

    expense_by_category: dict[str, float] = {}
    income_by_category:  dict[str, float] = {}
    expense_by_day:      dict[str, float] = {}
    income_by_day:       dict[str, float] = {}

    for t in expenses:
        expense_by_category[t["category"]] = expense_by_category.get(t["category"], 0) + t["amount"]
        day = datetime.fromisoformat(t["datetime"]).strftime("%Y-%m-%d")
        expense_by_day[day] = expense_by_day.get(day, 0) + t["amount"]

    for t in incomes:
        income_by_category[t["category"]] = income_by_category.get(t["category"], 0) + t["amount"]
        day = datetime.fromisoformat(t["datetime"]).strftime("%Y-%m-%d")
        income_by_day[day] = income_by_day.get(day, 0) + t["amount"]

    total_expense = sum(expense_by_category.values())
    total_income  = sum(income_by_category.values())

    return {
        "total_income":        total_income,
        "total_expense":       total_expense,
        "balance":             total_income - total_expense,
        "transaction_count":   len(month_txs),
        "expense_by_category": expense_by_category,
        "income_by_category":  income_by_category,
        "expense_by_day":      expense_by_day,
        "income_by_day":       income_by_day,
    }


@router.get("/categories")
async def list_categories(x_init_data: str = Header(...)):
    """Списки категорий расходов и доходов."""
    require_auth(x_init_data)
    return {
        "expense_categories": CATEGORIES,
        "income_categories":  INCOME_CATEGORIES,
    }


@router.get("/plan")
async def get_plan(x_init_data: str = Header(...)):
    """Возвращает текущий план юзера, лимиты и использование за период."""
    from services import plans, storage
    telegram_id = require_auth(x_init_data)
    user = ensure_user(x_init_data, telegram_id)

    plan = plans.effective_plan(user)
    plan_limits = plans.LIMITS.get(plan, {})

    def _used(action: str) -> int:
        period = plans.period_for(action)
        if action == "transaction":
            return (storage.count_transactions_today(telegram_id, source="text")
                    if period == "day"
                    else storage.count_transactions_this_month(telegram_id, source="text"))
        if action == "photo":
            return (storage.count_transactions_today(telegram_id, source="photo")
                    if period == "day"
                    else storage.count_transactions_this_month(telegram_id, source="photo"))
        if action == "ai_question":
            return (storage.count_events_today(telegram_id, "ai_question")
                    if period == "day"
                    else storage.count_events_this_month(telegram_id, "ai_question"))
        if action == "voice":
            return (storage.count_events_today(telegram_id, "voice")
                    if period == "day"
                    else storage.count_events_this_month(telegram_id, "voice"))
        return 0

    runtime_actions = ["transaction", "photo", "ai_question", "voice"]
    usage = {}
    for a in runtime_actions:
        usage[a] = {
            "used":   _used(a),
            "limit":  plans.limit_for(plan, a),
            "period": plans.period_for(a),
        }

    import os
    bot_username = os.environ.get("BOT_USERNAME", "smartcash_ai_bot")
    referral_code = user.get("referral_code") or ""
    invite_link = f"https://t.me/{bot_username}?start=ref_{referral_code}" if referral_code else ""

    return {
        "plan":               plan,
        "plan_title":         plans.PLAN_TITLE.get(plan, plan),
        "trial_until":        user.get("trial_until"),
        "subscription_until": user.get("subscription_until"),
        "limits":             plan_limits,
        "usage":              usage,
        "pricing": {
            plans.PLAN_PREMIUM: {"stars": plans.PRICE_STARS[plans.PLAN_PREMIUM], "usd": plans.PRICE_USD[plans.PLAN_PREMIUM]},
            plans.PLAN_PRO:     {"stars": plans.PRICE_STARS[plans.PLAN_PRO],     "usd": plans.PRICE_USD[plans.PLAN_PRO]},
        },
        "referral": {
            "code":         referral_code,
            "invite_link":  invite_link,
            "bonus_days":   14,
        },
    }


@router.post("/upgrade/invoice")
async def create_upgrade_invoice(
    body: dict,
    x_init_data: str = Header(...),
):
    """
    Создаёт Telegram Stars invoice link для апгрейда подписки.
    Body: { "tier": "premium" | "pro" }
    Возвращает: { "invoice_link": "https://t.me/$..." }
    """
    import os
    import httpx
    from services import plans, storage

    telegram_id = require_auth(x_init_data)
    user = ensure_user(x_init_data, telegram_id)

    tier = (body or {}).get("tier")
    if tier not in (plans.PLAN_PREMIUM, plans.PLAN_PRO):
        raise HTTPException(status_code=400, detail="Invalid tier")

    stars = plans.PRICE_STARS.get(tier)
    if not stars:
        raise HTTPException(status_code=400, detail="No price for tier")

    bot_token = os.environ.get("BOT_TOKEN")
    if not bot_token:
        raise HTTPException(status_code=500, detail="Bot misconfigured")

    title = "AI-Финансист — Premium" if tier == plans.PLAN_PREMIUM else "AI-Финансист — Pro"
    description = (
        "Premium на 30 дней: 17 трат/день, 30 фото/мес, 300 вопросов AI."
        if tier == plans.PLAN_PREMIUM
        else "Pro на 30 дней: 100 трат/день, 150 фото/мес, 1500 вопросов AI, экспорт 10/мес."
    )

    payload = f"{tier}:{telegram_id}"
    storage.log_event(telegram_id, "upgrade_clicked", {"tier": tier, "source": "miniapp"})

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{bot_token}/createInvoiceLink",
            json={
                "title": title,
                "description": description,
                "payload": payload,
                "provider_token": "",
                "currency": "XTR",
                "prices": [{"label": title, "amount": stars}],
            },
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Telegram API error: {resp.text[:200]}")
    data = resp.json()
    if not data.get("ok"):
        raise HTTPException(status_code=502, detail=f"createInvoiceLink: {data.get('description', 'unknown')}")

    return {"invoice_link": data["result"]}
