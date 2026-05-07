from datetime import datetime


def format_amount(amount: float, currency: str = "KGS") -> str:
    """Форматирует сумму с валютой. Убирает дробную часть если она нулевая."""
    if amount == int(amount):
        return f"{int(amount)} {currency}"
    return f"{amount:.2f} {currency}"


def format_date(dt: datetime) -> str:
    """Форматирует дату на русском языке (например: '7 мая')."""
    months = [
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря"
    ]
    return f"{dt.day} {months[dt.month - 1]}"
