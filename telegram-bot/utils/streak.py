"""Подсчёт streak — последовательных дней с записями.

Используется в /today и /stats как retention-механика (Duolingo-стиль):
юзер видит «🔥 N дней подряд» и не хочет прерывать счётчик.
"""
from datetime import date, datetime, timedelta


def compute_streak_days(transactions: list[dict], today: date | None = None) -> int:
    """Считает сколько дней подряд (от сегодня или вчера) есть хотя бы одна транзакция.

    Если сегодня уже была запись — стартуем от сегодня. Если нет, но вчера была —
    стартуем от вчера (даём юзеру шанс не потерять streak до конца дня).
    Если и сегодня, и вчера ничего — streak=0.
    """
    if not transactions:
        return 0

    today = today or date.today()
    tx_dates: set[date] = set()
    for t in transactions:
        try:
            d = datetime.fromisoformat(str(t["datetime"]).replace("Z", "+00:00")).date()
            tx_dates.add(d)
        except Exception:
            continue

    if today in tx_dates:
        start = today
    elif (today - timedelta(days=1)) in tx_dates:
        start = today - timedelta(days=1)
    else:
        return 0

    streak = 0
    current = start
    while current in tx_dates:
        streak += 1
        current -= timedelta(days=1)
    return streak


def format_streak(days: int, today_logged: bool) -> str:
    """Возвращает строку для UI типа «🔥 5 дней подряд» или подсказку для пустого дня.

    today_logged — есть ли запись СЕГОДНЯ. Если streak ≥ 1 но today_logged=False,
    напоминаем что нужно записать сегодня иначе streak обнулится.
    """
    if days == 0:
        return ""
    if days == 1:
        return "🔥 1 день подряд — начало серии!"
    word = "дня" if 2 <= days <= 4 else "дней"
    base = f"🔥 {days} {word} подряд"
    if not today_logged:
        return f"{base} — запиши сегодня, чтобы не потерять"
    return f"{base} — так держать!"
