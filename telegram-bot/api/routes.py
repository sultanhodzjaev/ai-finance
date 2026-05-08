import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Header

from api.auth import get_telegram_id
from services.storage import (
    get_user, get_transactions, get_transaction,
    update_transaction, delete_transaction, add_transaction,
    get_or_create_user,
)
from utils.categories import CATEGORIES

router = APIRouter(prefix="/miniapp/api")


def require_auth(init_data: str) -> int:
    """Извлекает telegram_id или выбрасывает 401."""
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
        "first_name": user["first_name"],
        "currency": user["currency"],
    }


@router.get("/transactions")
async def list_transactions(x_init_data: str = Header(...)):
    """Все транзакции пользователя, от новых к старым."""
    telegram_id = require_auth(x_init_data)
    txs = get_transactions(telegram_id)
    return {"transactions": sorted(txs, key=lambda t: t["datetime"], reverse=True)}


@router.post("/transactions")
async def create_transaction(payload: dict, x_init_data: str = Header(...)):
    """Создать транзакцию из Mini App (без AI)."""
    telegram_id = require_auth(x_init_data)
    tx = {
        "id": str(uuid.uuid4()),
        "amount": float(payload["amount"]),
        "category": payload.get("category", "other"),
        "description": payload.get("description", ""),
        "merchant": None,
        "datetime": datetime.now().isoformat(),
        "source": "miniapp",
    }
    add_transaction(telegram_id, tx)
    return tx


@router.patch("/transactions/{tx_id}")
async def edit_transaction(
    tx_id: str, payload: dict, x_init_data: str = Header(...)
):
    """Обновить сумму, категорию или описание транзакции."""
    telegram_id = require_auth(x_init_data)
    allowed = {"amount", "category", "description"}
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
    """Статистика по категориям и по дням за текущий месяц."""
    telegram_id = require_auth(x_init_data)
    txs = get_transactions(telegram_id)
    now = datetime.now()
    month_txs = [
        t for t in txs
        if datetime.fromisoformat(t["datetime"]).month == now.month
        and datetime.fromisoformat(t["datetime"]).year == now.year
    ]

    by_category: dict[str, float] = {}
    by_day: dict[str, float] = {}
    for t in month_txs:
        by_category[t["category"]] = by_category.get(t["category"], 0) + t["amount"]
        day = datetime.fromisoformat(t["datetime"]).strftime("%Y-%m-%d")
        by_day[day] = by_day.get(day, 0) + t["amount"]

    return {
        "total": sum(by_category.values()),
        "transaction_count": len(month_txs),
        "by_category": by_category,
        "by_day": by_day,
    }


@router.get("/categories")
async def list_categories(x_init_data: str = Header(...)):
    """Список доступных категорий."""
    require_auth(x_init_data)
    return {"categories": CATEGORIES}
