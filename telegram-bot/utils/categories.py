# Фиксированный список категорий с эмодзи
CATEGORIES = [
    {"id": "food", "name": "Еда", "emoji": "🍕"},
    {"id": "groceries", "name": "Продукты", "emoji": "🛒"},
    {"id": "transport", "name": "Транспорт", "emoji": "🚗"},
    {"id": "entertainment", "name": "Развлечения", "emoji": "🎬"},
    {"id": "health", "name": "Здоровье", "emoji": "💊"},
    {"id": "clothes", "name": "Одежда", "emoji": "👕"},
    {"id": "home", "name": "Жильё", "emoji": "🏠"},
    {"id": "communication", "name": "Связь", "emoji": "📱"},
    {"id": "gifts", "name": "Подарки", "emoji": "🎁"},
    {"id": "other", "name": "Другое", "emoji": "📦"},
]

# Словарь для быстрого поиска по id
CATEGORIES_BY_ID = {cat["id"]: cat for cat in CATEGORIES}


def get_category(category_id: str) -> dict:
    """Возвращает категорию по id, или 'other' если не найдена."""
    return CATEGORIES_BY_ID.get(category_id, CATEGORIES_BY_ID["other"])


def get_category_display(category_id: str) -> str:
    """Возвращает строку вида '🍕 Еда' для отображения."""
    cat = get_category(category_id)
    return f"{cat['emoji']} {cat['name']}"
