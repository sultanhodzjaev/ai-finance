import uuid

# Глобальный словарь — единственное хранилище данных.
# Все данные хранятся только в памяти процесса и сбрасываются при перезапуске.
# Бот и Mini App работают с одним и тем же объектом _storage в одном процессе.
_storage: dict = {
    "users": {}
}


def get_user(telegram_id: int) -> dict | None:
    """Возвращает пользователя по Telegram ID или None если не зарегистрирован."""
    return _storage["users"].get(telegram_id)


def create_user(telegram_id: int, username: str, first_name: str) -> dict:
    """Создаёт нового пользователя и сохраняет его в памяти."""
    user = {
        "telegram_id": telegram_id,
        "username": username,
        "first_name": first_name,
        "currency": "KGS",
        "transactions": []
    }
    _storage["users"][telegram_id] = user
    return user


def get_or_create_user(telegram_id: int, username: str, first_name: str) -> dict:
    """Возвращает существующего пользователя или создаёт нового."""
    user = get_user(telegram_id)
    if user is None:
        user = create_user(telegram_id, username, first_name)
    return user


def add_transaction(telegram_id: int, transaction: dict) -> None:
    """Добавляет транзакцию в список пользователя.
    Если транзакция не содержит id — генерирует UUID автоматически.
    """
    if "id" not in transaction:
        transaction = {**transaction, "id": str(uuid.uuid4())}
    _storage["users"][telegram_id]["transactions"].append(transaction)


def get_transactions(telegram_id: int) -> list:
    """Возвращает все транзакции пользователя."""
    user = get_user(telegram_id)
    return user["transactions"] if user else []


def get_transaction(telegram_id: int, transaction_id: str) -> dict | None:
    """Получить одну транзакцию по ID."""
    user = get_user(telegram_id)
    if not user:
        return None
    for tx in user["transactions"]:
        if tx["id"] == transaction_id:
            return tx
    return None


def update_transaction(telegram_id: int, transaction_id: str, updates: dict) -> dict | None:
    """Обновить поля транзакции (amount, category, description)."""
    user = get_user(telegram_id)
    if not user:
        return None
    for tx in user["transactions"]:
        if tx["id"] == transaction_id:
            tx.update(updates)
            return tx
    return None


def delete_transaction(telegram_id: int, transaction_id: str) -> bool:
    """Удалить транзакцию по ID. Возвращает True если транзакция была найдена и удалена."""
    user = get_user(telegram_id)
    if not user:
        return False
    before = len(user["transactions"])
    user["transactions"] = [tx for tx in user["transactions"] if tx["id"] != transaction_id]
    return len(user["transactions"]) < before
