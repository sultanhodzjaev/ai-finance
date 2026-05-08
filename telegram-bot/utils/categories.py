# Категории расходов (10 штук)
CATEGORIES = [
    {"id": "food",          "name": "Еда",           "emoji": "🍕"},
    {"id": "groceries",     "name": "Продукты",       "emoji": "🛒"},
    {"id": "transport",     "name": "Транспорт",      "emoji": "🚗"},
    {"id": "entertainment", "name": "Развлечения",    "emoji": "🎬"},
    {"id": "health",        "name": "Здоровье",       "emoji": "💊"},
    {"id": "clothes",       "name": "Одежда",         "emoji": "👕"},
    {"id": "home",          "name": "Жильё",          "emoji": "🏠"},
    {"id": "communication", "name": "Связь",          "emoji": "📱"},
    {"id": "gifts",         "name": "Подарки",        "emoji": "🎁"},
    {"id": "other",         "name": "Другое",         "emoji": "📦"},
]

# Категории доходов (6 штук)
INCOME_CATEGORIES = [
    {"id": "salary",       "name": "Зарплата",    "emoji": "💼"},
    {"id": "freelance",    "name": "Фриланс",     "emoji": "💻"},
    {"id": "business",     "name": "Бизнес",      "emoji": "📈"},
    {"id": "investment",   "name": "Инвестиции",  "emoji": "📊"},
    {"id": "gift_income",  "name": "Подарок",     "emoji": "🎁"},
    {"id": "other_income", "name": "Другое",      "emoji": "💰"},
]

# Словари для быстрого поиска
CATEGORIES_BY_ID       = {cat["id"]: cat for cat in CATEGORIES}
INCOME_CATEGORIES_BY_ID = {cat["id"]: cat for cat in INCOME_CATEGORIES}


def get_category(category_id: str) -> dict:
    """Возвращает категорию расходов по id, или 'other' если не найдена."""
    return CATEGORIES_BY_ID.get(category_id, CATEGORIES_BY_ID["other"])


def get_category_by_id(category_id: str) -> dict | None:
    """Ищет категорию по id в обоих списках (расходы + доходы)."""
    return (
        CATEGORIES_BY_ID.get(category_id)
        or INCOME_CATEGORIES_BY_ID.get(category_id)
    )


def get_category_display(category_id: str) -> str:
    """Возвращает строку вида '🍕 Еда' для отображения."""
    cat = get_category(category_id)
    return f"{cat['emoji']} {cat['name']}"
