# Глобальный словарь — единственное хранилище данных.
# Все данные хранятся только в памяти процесса и сбрасываются при перезапуске.
# Никаких файлов, никаких БД — всё в оперативной памяти.
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
    """Добавляет транзакцию в список пользователя."""
    _storage["users"][telegram_id]["transactions"].append(transaction)


def get_transactions(telegram_id: int) -> list:
    """Возвращает все транзакции пользователя."""
    user = get_user(telegram_id)
    return user["transactions"] if user else []
