import logging
from datetime import datetime, date

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from services import storage
from utils.categories import get_category
from utils.formatters import format_amount, format_date

logger = logging.getLogger(__name__)
router = Router()

# Названия месяцев для заголовков на русском
MONTH_NAMES_GEN = [
    "январе", "феврале", "марте", "апреле", "мае", "июне",
    "июле", "августе", "сентябре", "октябре", "ноябре", "декабре"
]
MONTH_NAMES_NOM = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
]


@router.message(Command("today"))
@router.callback_query(F.data == "show_today")
async def cmd_today(event: Message | CallbackQuery):
    """Показывает все траты пользователя за сегодня."""
    if isinstance(event, CallbackQuery):
        user_id = event.from_user.id
        send = event.message.answer
        await event.answer()
    else:
        user_id = event.from_user.id
        send = event.answer

    user = storage.get_or_create_user(user_id, "", "")
    transactions = storage.get_transactions(user_id)
    currency = user.get("currency", "KGS")

    # Фильтруем транзакции за сегодня
    today = date.today()
    today_transactions = []
    for t in transactions:
        try:
            t_date = datetime.fromisoformat(t["datetime"]).date()
            if t_date == today:
                today_transactions.append(t)
        except Exception:
            pass

    if not today_transactions:
        await send(
            "Сегодня ты ещё ничего не записал. "
            "Так держать или забыл записать? 😄"
        )
        return

    today_dt = datetime.today()
    lines = [f"📅 Сегодня, {format_date(today_dt)}\n"]
    total = 0.0

    for t in today_transactions:
        cat = get_category(t.get("category", "other"))
        amount = t.get("amount", 0)
        total += amount
        desc = f" ({t['description']})" if t.get("description") else ""
        lines.append(f"{cat['emoji']} {cat['name']} — {format_amount(amount, currency)}{desc}")

    lines.append(f"\n💰 Всего потрачено: {format_amount(total, currency)}")
    await send("\n".join(lines))


@router.message(Command("stats"))
@router.callback_query(F.data == "show_stats")
async def cmd_stats(event: Message | CallbackQuery):
    """Показывает статистику трат за текущий месяц."""
    if isinstance(event, CallbackQuery):
        user_id = event.from_user.id
        send = event.message.answer
        await event.answer()
    else:
        user_id = event.from_user.id
        send = event.answer

    user = storage.get_or_create_user(user_id, "", "")
    transactions = storage.get_transactions(user_id)
    currency = user.get("currency", "KGS")

    now = datetime.now()
    current_month = now.month
    current_year = now.year

    # Фильтруем транзакции за текущий месяц
    month_transactions = []
    for t in transactions:
        try:
            dt = datetime.fromisoformat(t["datetime"])
            if dt.month == current_month and dt.year == current_year:
                month_transactions.append(t)
        except Exception:
            pass

    if not month_transactions:
        await send(
            f"В {MONTH_NAMES_GEN[current_month - 1]} ты ещё ничего не записал."
        )
        return

    # Считаем итоги по категориям
    categories_totals: dict[str, float] = {}
    total = 0.0
    for t in month_transactions:
        cat_id = t.get("category", "other")
        amount = t.get("amount", 0)
        categories_totals[cat_id] = categories_totals.get(cat_id, 0) + amount
        total += amount

    # Среднее в день (от начала месяца до сегодня)
    days_elapsed = now.day
    avg_per_day = total / days_elapsed if days_elapsed > 0 else 0

    month_name = MONTH_NAMES_NOM[current_month - 1]
    lines = [f"📊 Статистика за {month_name}\n"]

    # Сортируем категории по убыванию суммы
    for cat_id, amount in sorted(categories_totals.items(), key=lambda x: -x[1]):
        cat = get_category(cat_id)
        percent = (amount / total * 100) if total > 0 else 0
        lines.append(
            f"{cat['emoji']} {cat['name']} — {format_amount(amount, currency)} ({percent:.0f}%)"
        )

    lines.append(f"\n💰 Всего: {format_amount(total, currency)}")
    lines.append(f"📈 Среднее в день: {format_amount(avg_per_day, currency)}")
    lines.append(f"🔢 Транзакций: {len(month_transactions)}")

    await send("\n".join(lines))
