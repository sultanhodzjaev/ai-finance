import logging
from datetime import datetime, date

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from services import plans, storage
from utils.categories import get_category, get_category_by_id
from utils.formatters import format_amount, format_date
from utils.streak import compute_streak_days, format_streak

logger = logging.getLogger(__name__)
router = Router()

MONTH_NAMES_GEN = [
    "январе", "феврале", "марте", "апреле", "мае", "июне",
    "июле", "августе", "сентябре", "октябре", "ноябре", "декабре",
]
MONTH_NAMES_NOM = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


def _switch_today_kb() -> InlineKeyboardMarkup:
    """Под /stats — переключение на /today."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📅 За сегодня", callback_data="show_today"),
    ]])


def _switch_month_kb() -> InlineKeyboardMarkup:
    """Под /today — переключение на /stats."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📈 За месяц", callback_data="show_stats"),
    ]])


@router.message(Command("today"))
@router.callback_query(F.data == "show_today")
async def cmd_today(event: Message | CallbackQuery):
    """Показывает доходы и расходы за сегодня с остатком."""
    if isinstance(event, CallbackQuery):
        user_id = event.from_user.id
        send = event.message.answer
        await event.answer()
    else:
        user_id = event.from_user.id
        send = event.answer

    user = storage.get_or_create_user(user_id, "", "")
    history_days = plans.LIMITS.get(plans.effective_plan(user), {}).get("history_days")
    transactions = storage.get_transactions(user_id, since_days=history_days)
    currency = user.get("currency", "KGS")

    today = date.today()
    today_txs = [
        t for t in transactions
        if _safe_date(t) == today
    ]

    streak = compute_streak_days(transactions, today=today)
    streak_line = format_streak(streak, today_logged=bool(today_txs))

    if not today_txs:
        # Если есть streak — подталкиваем не потерять его сегодня; иначе обычный текст.
        hint = streak_line if streak_line else "Так держать или забыл записать? 😄"
        await send(
            f"Сегодня ты ещё ничего не записал.\n{hint}",
            reply_markup=_switch_month_kb(),
        )
        return

    today_dt = datetime.today()
    incomes  = [t for t in today_txs if t.get("type") == "income"]
    expenses = [t for t in today_txs if t.get("type", "expense") == "expense"]

    total_income  = sum(t["amount"] for t in incomes)
    total_expense = sum(t["amount"] for t in expenses)
    balance       = total_income - total_expense

    lines = [f"📅 Сегодня, {format_date(today_dt)}\n"]

    # --- Секция доходов ---
    if incomes:
        lines.append("💰 ДОХОДЫ")
        for t in incomes:
            cat  = get_category_by_id(t.get("category", "other")) or {"emoji": "💰", "name": "Доход"}
            desc = f" ({t['description']})" if t.get("description") else ""
            lines.append(f"{cat['emoji']} {cat['name']} — +{format_amount(t['amount'], currency)}{desc}")
        lines.append(f"📊 Итого доходов: {format_amount(total_income, currency)}\n")

    # --- Секция расходов ---
    if expenses:
        lines.append("💸 РАСХОДЫ")
        for t in expenses:
            cat  = get_category_by_id(t.get("category", "other")) or {"emoji": "📦", "name": "Другое"}
            desc = f" ({t['description']})" if t.get("description") else ""
            lines.append(f"{cat['emoji']} {cat['name']} — {format_amount(t['amount'], currency)}{desc}")
        lines.append(f"📊 Итого расходов: {format_amount(total_expense, currency)}\n")

    # --- Итоговый остаток ---
    sign = "+" if balance >= 0 else ""
    emoji = "✅" if balance >= 0 else "⚠️"
    lines.append(f"{emoji} Остаток за день: {sign}{format_amount(balance, currency)}")
    if streak_line:
        lines.append(streak_line)

    await send("\n".join(lines), reply_markup=_switch_month_kb())


@router.message(Command("stats"))
@router.callback_query(F.data == "show_stats")
async def cmd_stats(event: Message | CallbackQuery):
    """Показывает статистику доходов и расходов за текущий месяц."""
    if isinstance(event, CallbackQuery):
        user_id = event.from_user.id
        send = event.message.answer
        await event.answer()
    else:
        user_id = event.from_user.id
        send = event.answer

    user = storage.get_or_create_user(user_id, "", "")
    history_days = plans.LIMITS.get(plans.effective_plan(user), {}).get("history_days")
    transactions = storage.get_transactions(user_id, since_days=history_days)
    currency = user.get("currency", "KGS")

    now = datetime.now()
    today_d = date.today()
    month_txs = [
        t for t in transactions
        if _safe_dt(t).month == now.month and _safe_dt(t).year == now.year
    ]
    streak = compute_streak_days(transactions, today=today_d)
    today_logged = any(_safe_date(t) == today_d for t in transactions)
    streak_line = format_streak(streak, today_logged=today_logged)

    if not month_txs:
        await send(
            f"В {MONTH_NAMES_GEN[now.month - 1]} ты ещё ничего не записал.",
            reply_markup=_switch_today_kb(),
        )
        return

    incomes  = [t for t in month_txs if t.get("type") == "income"]
    expenses = [t for t in month_txs if t.get("type", "expense") == "expense"]

    # Считаем итоги по категориям
    income_by_cat: dict[str, float]  = {}
    expense_by_cat: dict[str, float] = {}
    for t in incomes:
        cat = t.get("category", "other_income")
        income_by_cat[cat] = income_by_cat.get(cat, 0) + t["amount"]
    for t in expenses:
        cat = t.get("category", "other")
        expense_by_cat[cat] = expense_by_cat.get(cat, 0) + t["amount"]

    total_income  = sum(income_by_cat.values())
    total_expense = sum(expense_by_cat.values())
    balance       = total_income - total_expense

    days_elapsed = now.day
    avg_per_day  = total_expense / days_elapsed if days_elapsed > 0 else 0

    month_name = MONTH_NAMES_NOM[now.month - 1]
    lines = [f"📊 Статистика за {month_name}\n"]

    # --- Секция доходов ---
    if incomes:
        lines.append("💰 ДОХОДЫ")
        for cat_id, amount in sorted(income_by_cat.items(), key=lambda x: -x[1]):
            cat     = get_category_by_id(cat_id) or {"emoji": "💰", "name": cat_id}
            percent = (amount / total_income * 100) if total_income > 0 else 0
            lines.append(f"{cat['emoji']} {cat['name']} — {format_amount(amount, currency)} ({percent:.0f}%)")
        lines.append(f"📊 Итого: {format_amount(total_income, currency)}\n")

    # --- Секция расходов ---
    if expenses:
        lines.append("💸 РАСХОДЫ")
        for cat_id, amount in sorted(expense_by_cat.items(), key=lambda x: -x[1]):
            cat     = get_category_by_id(cat_id) or {"emoji": "📦", "name": cat_id}
            percent = (amount / total_expense * 100) if total_expense > 0 else 0
            lines.append(f"{cat['emoji']} {cat['name']} — {format_amount(amount, currency)} ({percent:.0f}%)")
        lines.append(f"📊 Итого: {format_amount(total_expense, currency)}\n")

    # --- Итоговые строки ---
    sign  = "+" if balance >= 0 else ""
    emoji = "✅" if balance >= 0 else "⚠️"
    lines.append(f"{emoji} Остаток за месяц: {sign}{format_amount(balance, currency)}")
    if expenses:
        lines.append(f"📈 Среднее в день (расходы): {format_amount(avg_per_day, currency)}")
    lines.append(f"🔢 Транзакций: {len(month_txs)}")
    if streak_line:
        lines.append(streak_line)

    await send("\n".join(lines), reply_markup=_switch_today_kb())


# ---- helpers ----

def _safe_date(t: dict) -> date:
    try:
        return datetime.fromisoformat(t["datetime"]).date()
    except Exception:
        return date.min


def _safe_dt(t: dict) -> datetime:
    try:
        return datetime.fromisoformat(t["datetime"])
    except Exception:
        return datetime.min
