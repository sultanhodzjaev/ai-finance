import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Query

from api.auth import get_telegram_id
from services.storage import (
    get_user, get_transactions, get_transaction,
    update_transaction, delete_transaction, add_transaction,
)
from utils.categories import CATEGORIES, INCOME_CATEGORIES

router = APIRouter(prefix="/miniapp/api")


def require_auth(init_data: str) -> int:
    telegram_id = get_telegram_id(init_data)
    if not telegram_id:
        raise HTTPException(status_code=401, detail="Invalid initData")
    return telegram_id


@router.get("/me")
async def get_me(x_init_data: str = Header(...)):
    """Данные текущего пользователя."""
    telegram_id = require_auth(x_init_data)
    user = get_user(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
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
    txs = get_transactions(telegram_id)

    # Обратная совместимость: транзакции без type считаются expense
    if type in ("income", "expense"):
        txs = [tx for tx in txs if tx.get("type", "expense") == type]

    return {"transactions": sorted(txs, key=lambda t: t["datetime"], reverse=True)}


@router.post("/transactions")
async def create_transaction(payload: dict, x_init_data: str = Header(...)):
    """Создать транзакцию из Mini App (без AI)."""
    telegram_id = require_auth(x_init_data)
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
        "total_income":          total_income,
        "total_expense":         total_expense,
        "balance":               total_income - total_expense,
        "transaction_count":     len(month_txs),
        "expense_by_category":   expense_by_category,
        "income_by_category":    income_by_category,
        "expense_by_day":        expense_by_day,
        "income_by_day":         income_by_day,
    }


@router.get("/categories")
async def list_categories(x_init_data: str = Header(...)):
    """Списки категорий расходов и доходов."""
    require_auth(x_init_data)
    return {
        "expense_categories": CATEGORIES,
        "income_categories":  INCOME_CATEGORIES,
    }
