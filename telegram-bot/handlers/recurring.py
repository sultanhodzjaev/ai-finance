"""Команды для управления регулярными платежами."""
import logging
import re
from datetime import datetime, timezone, timedelta

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from services import plans, storage
from utils.categories import CATEGORIES, INCOME_CATEGORIES, get_category_by_id
from utils.formatters import format_amount

logger = logging.getLogger(__name__)
router = Router()


class AddRec(StatesGroup):
    """Шаговый диалог для /addrec. Порядок шагов изменён, чтобы тип спрашивался до
    категории — категория зависит от типа (расход/доход — разные клавиатуры)."""
    waiting_amount = State()
    waiting_type = State()
    waiting_category = State()
    waiting_period = State()
    waiting_description = State()


def _cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Отмена", callback_data="addrec_cancel"),
    ]])


def _period_kb() -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton(text="Каждые 7 дней",  callback_data="addrec_period:7"),
        InlineKeyboardButton(text="14 дней", callback_data="addrec_period:14"),
    ], [
        InlineKeyboardButton(text="30 дней (месяц)", callback_data="addrec_period:30"),
        InlineKeyboardButton(text="90 дней (квартал)", callback_data="addrec_period:90"),
    ], [
        InlineKeyboardButton(text="Своё число", callback_data="addrec_period:custom"),
        InlineKeyboardButton(text="Отмена", callback_data="addrec_cancel"),
    ]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _description_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Пропустить", callback_data="addrec_skip_desc"),
        InlineKeyboardButton(text="Отмена",     callback_data="addrec_cancel"),
    ]])


def _type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💸 Расход", callback_data="addrec_type:expense"),
        InlineKeyboardButton(text="💰 Доход",  callback_data="addrec_type:income"),
    ], [
        InlineKeyboardButton(text="Отмена", callback_data="addrec_cancel"),
    ]])


def _category_kb(type_: str) -> InlineKeyboardMarkup:
    """Клавиатура категорий — 2 колонки, отдельные списки для расходов/доходов."""
    cats = CATEGORIES if type_ == "expense" else INCOME_CATEGORIES
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for cat in cats:
        pair.append(InlineKeyboardButton(
            text=f"{cat['emoji']} {cat['name']}",
            callback_data=f"addrec_cat:{cat['id']}",
        ))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="addrec_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _limit_for_user(telegram_id: int) -> int:
    user = storage.get_user(telegram_id) or {}
    plan = plans.effective_plan(user)
    return plans.LIMITS.get(plan, {}).get("recurring_payments_max", 0) or 0


def _format_recurring_category(cat_value: str) -> str:
    """Возвращает '🍕 Еда' для известного category_id, иначе исходную строку (legacy)."""
    cat = get_category_by_id(cat_value)
    if cat:
        return f"{cat['emoji']} {cat['name']}"
    return cat_value


async def _send_myrec(user_id: int, send) -> None:
    """Общая логика /myrec и callback rec_list."""
    rps = storage.get_recurring_payments(user_id, only_active=True)
    if not rps:
        await send(
            "У тебя пока нет регулярных платежей.\n\n"
            "Добавить — просто нажми /addrec, бот спросит сумму, категорию и период по шагам.",
        )
        return

    user = storage.get_user(user_id) or {}
    currency = user.get("currency") or "KGS"

    lines = ["🔁 <b>Регулярные платежи:</b>\n"]
    rows = []
    for r in rps:
        next_at = r["next_run_at"][:10]
        kind = "доход" if r["type"] == "income" else "расход"
        cat_view = _format_recurring_category(r['category'])
        amount_view = format_amount(float(r['amount']), currency)
        lines.append(
            f"• <b>{amount_view}</b> · {cat_view} · каждые {r['period_days']} дн · {kind}\n"
            f"  Следующая: {next_at}\n"
            f"  «{r['description'] or '—'}»"
        )
        rows.append([InlineKeyboardButton(
            text=f"🗑 {amount_view} · {cat_view}",
            callback_data=f"delrec:{r['id']}",
        )])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await send("\n".join(lines), parse_mode="HTML", reply_markup=kb)


@router.message(Command("myrec"))
async def cmd_myrec(message: Message):
    await _send_myrec(message.from_user.id, message.answer)


@router.callback_query(F.data == "rec_list")
async def cb_rec_list(callback: CallbackQuery):
    await _send_myrec(callback.from_user.id, callback.message.answer)
    await callback.answer()


async def _start_addrec(uid: int, send, state: FSMContext) -> None:
    """Общая логика /addrec и callback rec_add."""
    cap = _limit_for_user(uid)
    have = storage.count_recurring_payments(uid)
    if cap and have >= cap:
        await send(
            f"Лимит регулярных платежей исчерпан ({have}/{cap}). Подними план — /upgrade",
            parse_mode="HTML",
        )
        storage.log_event(uid, "limit_hit", {"action": "recurring_create", "used": have, "limit": cap})
        return

    await state.set_state(AddRec.waiting_amount)
    await send(
        "💵 <b>Новый регулярный платёж</b>\n\n"
        "Шаг 1/5. Введи <b>сумму</b> (числом):",
        parse_mode="HTML",
        reply_markup=_cancel_kb(),
    )


@router.message(Command("addrec"))
async def cmd_addrec(message: Message, state: FSMContext):
    await _start_addrec(message.from_user.id, message.answer, state)


@router.callback_query(F.data == "rec_add")
async def cb_rec_add(callback: CallbackQuery, state: FSMContext):
    await _start_addrec(callback.from_user.id, callback.message.answer, state)
    await callback.answer()


@router.message(AddRec.waiting_amount)
async def _addrec_amount(message: Message, state: FSMContext):
    raw = (message.text or "").strip().replace(",", ".").replace(" ", "")
    try:
        amount = float(raw)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Сумма должна быть положительным числом. Например: <code>8750</code>", parse_mode="HTML", reply_markup=_cancel_kb())
        return
    await state.update_data(amount=amount)
    await state.set_state(AddRec.waiting_type)
    await message.answer(
        "Шаг 2/5. Это <b>расход</b> или <b>доход</b>?",
        parse_mode="HTML",
        reply_markup=_type_kb(),
    )


@router.callback_query(F.data.startswith("addrec_type:"), AddRec.waiting_type)
async def _addrec_type(callback: CallbackQuery, state: FSMContext):
    type_ = callback.data.split(":", 1)[1]
    if type_ not in ("expense", "income"):
        await callback.answer("Неверный тип", show_alert=True)
        return
    await state.update_data(type=type_)
    await state.set_state(AddRec.waiting_category)
    await callback.answer()
    await callback.message.answer(
        "Шаг 3/5. Выбери <b>категорию</b>:",
        parse_mode="HTML",
        reply_markup=_category_kb(type_),
    )


@router.callback_query(F.data.startswith("addrec_cat:"), AddRec.waiting_category)
async def _addrec_category_btn(callback: CallbackQuery, state: FSMContext):
    cat_id = callback.data.split(":", 1)[1]
    if get_category_by_id(cat_id) is None:
        await callback.answer("Неизвестная категория", show_alert=True)
        return
    await state.update_data(category=cat_id)
    await state.set_state(AddRec.waiting_period)
    await callback.answer()
    await callback.message.answer(
        "Шаг 4/5. Как часто списывать?",
        reply_markup=_period_kb(),
    )


@router.callback_query(F.data.startswith("addrec_period:"), AddRec.waiting_period)
async def _addrec_period_btn(callback: CallbackQuery, state: FSMContext):
    value = callback.data.split(":", 1)[1]
    if value == "custom":
        await callback.answer()
        await callback.message.answer("Введи число дней (1–365):", reply_markup=_cancel_kb())
        return
    try:
        days = int(value)
    except ValueError:
        await callback.answer("Неверный период", show_alert=True)
        return
    await state.update_data(period_days=days)
    await callback.answer()
    await state.set_state(AddRec.waiting_description)
    await callback.message.answer(
        "Шаг 5/5. <b>Описание</b> (например, «Spotify») — или нажми «Пропустить»:",
        parse_mode="HTML",
        reply_markup=_description_kb(),
    )


@router.message(AddRec.waiting_period)
async def _addrec_period_text(message: Message, state: FSMContext):
    try:
        days = int((message.text or "").strip())
        if not 1 <= days <= 365:
            raise ValueError
    except ValueError:
        await message.answer("Число дней должно быть от 1 до 365.", reply_markup=_period_kb())
        return
    await state.update_data(period_days=days)
    await state.set_state(AddRec.waiting_description)
    await message.answer(
        "Шаг 5/5. <b>Описание</b> (например, «Spotify») — или нажми «Пропустить»:",
        parse_mode="HTML",
        reply_markup=_description_kb(),
    )


async def _create_recurring_and_reply(target, state: FSMContext, description: str) -> None:
    """Финальный шаг — берёт все данные из state, создаёт запись и пишет подтверждение.
    target — Message или CallbackQuery; ответ шлём через .answer/.message.answer."""
    data = await state.get_data()
    await state.clear()

    if isinstance(target, CallbackQuery):
        uid = target.from_user.id
        send = target.message.answer
    else:
        uid = target.from_user.id
        send = target.answer

    type_ = data.get("type", "expense")
    first_run = datetime.now(timezone.utc) + timedelta(days=int(data["period_days"]))
    rp = storage.add_recurring_payment(
        uid,
        type_=type_,
        amount=float(data["amount"]),
        category=data["category"],
        description=description,
        period_days=int(data["period_days"]),
        first_run_at=first_run,
    )
    if not rp:
        await send("Не получилось создать. Попробуй ещё раз: /addrec")
        return

    user = storage.get_user(uid) or {}
    currency = user.get("currency") or "KGS"
    cat = get_category_by_id(data["category"]) or {"emoji": "📦", "name": data["category"]}
    kind = "доход" if type_ == "income" else "расход"
    desc_line = description or "—"
    await send(
        f"✅ Регулярный <b>{kind}</b> создан.\n\n"
        f"Сумма: <b>{format_amount(float(data['amount']), currency)}</b>\n"
        f"Категория: {cat['emoji']} {cat['name']}\n"
        f"Период: каждые {data['period_days']} дн.\n"
        f"Описание: «{desc_line}»\n"
        f"Первое списание: <b>{first_run.strftime('%Y-%m-%d')}</b>\n\n"
        f"Список — /myrec",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "addrec_skip_desc", AddRec.waiting_description)
async def _addrec_skip_desc(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _create_recurring_and_reply(callback, state, description="")


@router.message(AddRec.waiting_description)
async def _addrec_description(message: Message, state: FSMContext):
    desc = (message.text or "").strip()[:200]
    await _create_recurring_and_reply(message, state, description=desc)


@router.callback_query(F.data == "addrec_cancel")
async def _addrec_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("Отменено")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer("Создание регулярного платежа отменено.")


async def _send_delrec_list(user_id: int, send) -> None:
    """Общая логика /delrec и callback rec_delete."""
    rps = storage.get_recurring_payments(user_id, only_active=True)
    if not rps:
        await send("У тебя нет регулярных платежей. Добавить — кнопка «➕ Добавить».")
        return
    user = storage.get_user(user_id) or {}
    currency = user.get("currency") or "KGS"
    rows = [[InlineKeyboardButton(
        text=f"🗑 {format_amount(float(r['amount']), currency)} · {_format_recurring_category(r['category'])} · каждые {r['period_days']} дн",
        callback_data=f"delrec:{r['id']}",
    )] for r in rps]
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="delrec_cancel")])
    await send("Какой регулярный платёж удалить?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(Command("delrec"))
async def cmd_delrec(message: Message):
    await _send_delrec_list(message.from_user.id, message.answer)


@router.callback_query(F.data == "rec_delete")
async def cb_rec_delete(callback: CallbackQuery):
    await _send_delrec_list(callback.from_user.id, callback.message.answer)
    await callback.answer()


@router.callback_query(F.data.startswith("delrec:"))
async def _delrec_click(callback: CallbackQuery):
    rp_id = callback.data.split(":", 1)[1]
    ok = storage.delete_recurring_payment(callback.from_user.id, rp_id)
    await callback.answer("Удалено" if ok else "Не найдено", show_alert=not ok)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer("Регулярный платёж удалён ✅" if ok else "Платёж не найден.")


@router.callback_query(F.data == "delrec_cancel")
async def _delrec_cancel(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
