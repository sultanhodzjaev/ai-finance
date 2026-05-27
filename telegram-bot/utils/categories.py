# Категории расходов (10 штук).
# emoji — для текстового UI в боте, icon — Lucide name для Mini App.
CATEGORIES = [
    {"id": "food",          "name": "Еда",           "emoji": "🍕", "icon": "utensils"},
    {"id": "groceries",     "name": "Продукты",       "emoji": "🛒", "icon": "shopping-cart"},
    {"id": "transport",     "name": "Транспорт",      "emoji": "🚗", "icon": "car"},
    {"id": "entertainment", "name": "Развлечения",    "emoji": "🎬", "icon": "clapperboard"},
    {"id": "health",        "name": "Здоровье",       "emoji": "💊", "icon": "heart-pulse"},
    {"id": "clothes",       "name": "Одежда",         "emoji": "👕", "icon": "shirt"},
    {"id": "home",          "name": "Жильё",          "emoji": "🏠", "icon": "home"},
    {"id": "communication", "name": "Связь",          "emoji": "📱", "icon": "smartphone"},
    {"id": "gifts",         "name": "Подарки",        "emoji": "🎁", "icon": "gift"},
    {"id": "other",         "name": "Другое",         "emoji": "📦", "icon": "package"},
]

# Категории доходов (6 штук)
INCOME_CATEGORIES = [
    {"id": "salary",       "name": "Зарплата",    "emoji": "💼", "icon": "briefcase"},
    {"id": "freelance",    "name": "Фриланс",     "emoji": "💻", "icon": "laptop"},
    {"id": "business",     "name": "Бизнес",      "emoji": "📈", "icon": "trending-up"},
    {"id": "investment",   "name": "Инвестиции",  "emoji": "📊", "icon": "bar-chart-3"},
    {"id": "gift_income",  "name": "Подарок",     "emoji": "🎁", "icon": "gift"},
    {"id": "other_income", "name": "Другое",      "emoji": "💰", "icon": "coins"},
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
