"""
Хранилище данных на Supabase (PostgreSQL).
Таблицы создаются автоматически при первом запуске через init_db().
"""
import logging
import os
import uuid
from datetime import datetime
from functools import lru_cache

from supabase import create_client, Client

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _client() -> Client:
    url = os.environ["SUPABASE_URL"]
    # service_role ключ обходит RLS — используем для серверного приложения
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_KEY"]
    return create_client(url, key)


# ---------------------------------------------------------------------------
# Инициализация схемы БД
# ---------------------------------------------------------------------------

def init_db() -> None:
    """
    Создаёт таблицы если их нет.
    Вызывается один раз при старте приложения.
    """
    sb = _client()
    # Проверяем наличие таблиц попыткой SELECT — если таблицы нет, поймаем ошибку
    try:
        sb.table("users").select("telegram_id").limit(1).execute()
        sb.table("transactions").select("id").limit(1).execute()
        logger.info("Supabase: таблицы уже существуют")
    except Exception:
        # Таблицы нужно создать через Supabase SQL editor или RPC
        # Здесь логируем, реальное создание — через SQL ниже
        logger.warning(
            "Supabase: таблицы не найдены — создай их через SQL Editor в Supabase Dashboard. "
            "SQL-скрипт находится в telegram-bot/supabase_schema.sql"
        )


# ---------------------------------------------------------------------------
# Пользователи
# ---------------------------------------------------------------------------

def get_user(telegram_id: int) -> dict | None:
    """Возвращает пользователя по Telegram ID или None."""
    try:
        res = _client().table("users").select("*").eq("telegram_id", telegram_id).maybe_single().execute()
        return res.data
    except Exception as e:
        logger.error(f"get_user({telegram_id}): {e}")
        return None


def create_user(telegram_id: int, username: str, first_name: str) -> dict:
    """Создаёт нового пользователя."""
    user = {
        "telegram_id": telegram_id,
        "username":    username,
        "first_name":  first_name,
        "currency":    "KGS",
    }
    try:
        res = _client().table("users").insert(user).execute()
        return res.data[0]
    except Exception as e:
        logger.error(f"create_user({telegram_id}): {e}")
        return {**user, "telegram_id": telegram_id}


def get_or_create_user(telegram_id: int, username: str, first_name: str) -> dict:
    """Возвращает существующего пользователя или создаёт нового."""
    user = get_user(telegram_id)
    if user is None:
        user = create_user(telegram_id, username, first_name)
    return user


# ---------------------------------------------------------------------------
# Транзакции
# ---------------------------------------------------------------------------

def add_transaction(telegram_id: int, transaction: dict) -> None:
    """Сохраняет транзакцию в БД."""
    if "id" not in transaction:
        transaction = {**transaction, "id": str(uuid.uuid4())}

    row = {
        "id":          transaction["id"],
        "telegram_id": telegram_id,
        "type":        transaction.get("type", "expense"),
        "amount":      float(transaction["amount"]),
        "category":    transaction.get("category", "other"),
        "description": transaction.get("description", ""),
        "merchant":    transaction.get("merchant"),
        "source":      transaction.get("source", "text"),
        "created_at":  transaction.get("datetime", datetime.now().isoformat()),
    }
    try:
        _client().table("transactions").insert(row).execute()
    except Exception as e:
        logger.error(f"add_transaction({telegram_id}): {e}")


def get_transactions(telegram_id: int) -> list:
    """Возвращает все транзакции пользователя, отсортированные от новых к старым."""
    try:
        res = (
            _client()
            .table("transactions")
            .select("*")
            .eq("telegram_id", telegram_id)
            .order("created_at", desc=True)
            .execute()
        )
        # Нормализуем поле datetime для обратной совместимости с ботом
        txs = []
        for row in (res.data or []):
            txs.append(_row_to_tx(row))
        return txs
    except Exception as e:
        logger.error(f"get_transactions({telegram_id}): {e}")
        return []


def get_transaction(telegram_id: int, transaction_id: str) -> dict | None:
    """Возвращает одну транзакцию по ID."""
    try:
        res = (
            _client()
            .table("transactions")
            .select("*")
            .eq("id", transaction_id)
            .eq("telegram_id", telegram_id)
            .maybe_single()
            .execute()
        )
        return _row_to_tx(res.data) if res.data else None
    except Exception as e:
        logger.error(f"get_transaction({transaction_id}): {e}")
        return None


def update_transaction(telegram_id: int, transaction_id: str, updates: dict) -> dict | None:
    """Обновляет поля транзакции."""
    # Переименовываем datetime → created_at если передан
    db_updates = {}
    for k, v in updates.items():
        if k == "datetime":
            db_updates["created_at"] = v
        else:
            db_updates[k] = v

    try:
        res = (
            _client()
            .table("transactions")
            .update(db_updates)
            .eq("id", transaction_id)
            .eq("telegram_id", telegram_id)
            .execute()
        )
        return _row_to_tx(res.data[0]) if res.data else None
    except Exception as e:
        logger.error(f"update_transaction({transaction_id}): {e}")
        return None


def delete_transaction(telegram_id: int, transaction_id: str) -> bool:
    """Удаляет транзакцию. Возвращает True если запись была найдена."""
    try:
        res = (
            _client()
            .table("transactions")
            .delete()
            .eq("id", transaction_id)
            .eq("telegram_id", telegram_id)
            .execute()
        )
        return len(res.data or []) > 0
    except Exception as e:
        logger.error(f"delete_transaction({transaction_id}): {e}")
        return False


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _row_to_tx(row: dict) -> dict:
    """Приводит строку БД к формату транзакции, совместимому с кодом бота."""
    return {
        "id":          row["id"],
        "type":        row.get("type", "expense"),
        "amount":      float(row["amount"]),
        "category":    row.get("category", "other"),
        "description": row.get("description", ""),
        "merchant":    row.get("merchant"),
        "source":      row.get("source", "text"),
        # поле datetime — для обратной совместимости с хендлерами бота
        "datetime":    row.get("created_at", datetime.now().isoformat()),
    }
