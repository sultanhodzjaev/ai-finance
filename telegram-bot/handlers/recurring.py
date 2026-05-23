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

logger = logging.getLogger(__name__)
router = Router()


class AddRec(StatesGroup):
    """Шаговый диалог для /addrec — упрощённая альтернатива однострочной команде."""
    waiting_amount = State()
    waiting_category = State()
    waiting_period = State()
    waiting_description = State()
    waiting_type = State()


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


def _limit_for_user(telegram_id: int) -> int:
    user = storage.get_user(telegram_id) or {}
    plan = plans.effective_plan(user)
    return plans.LIMITS.get(plan, {}).get("recurring_payments_max", 0) or 0


@router.message(Command("myrec"))
async def cmd_myrec(message: Message):
    """Список регулярных платежей."""
    rps = storage.get_recurring_payments(message.from_user.id, only_active=True)
    if not rps:
        await message.answer(
            "У тебя пока нет регулярных платежей.\n\n"
            "Добавить — просто нажми /addrec, бот спросит сумму, категорию и период по шагам.",
        )
        return
    lines = ["🔁 <b>Регулярные платежи:</b>\n"]
    for r in rps:
        next_at = r["next_run_at"][:10]
        kind = "доход" if r["type"] == "income" else "расход"
        lines.append(
            f"• <b>{r['amount']}</b> · {r['category']} · каждые {r['period_days']} дн · {kind}\n"
            f"  Следующая: {next_at}\n"
            f"  «{r['description'] or '—'}»\n"
            f"  <code>/delrec {r['id']}</code>"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("addrec"))
async def cmd_addrec(message: Message, state: FSMContext):
    """Запуск пошагового диалога добавления регулярного платежа."""
    # Лимит проверяем сразу — не тратим время юзера если упрётся в потолок
    uid = message.from_user.id
    cap = _limit_for_user(uid)
    have = storage.count_recurring_payments(uid)
    if cap and have >= cap:
        await message.answer(
            f"Лимит регулярных платежей исчерпан ({have}/{cap}). Подними план — /upgrade",
            parse_mode="HTML",
        )
        storage.log_event(uid, "limit_hit", {"action": "recurring_create", "used": have, "limit": cap})
        return

    await state.set_state(AddRec.waiting_amount)
    await message.answer(
        "💵 <b>Новый регулярный платёж</b>\n\n"
        "Шаг 1/5. Введи <b>сумму</b> (числом):",
        parse_mode="HTML",
        reply_markup=_cancel_kb(),
    )


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
    await state.set_state(AddRec.waiting_category)
    await message.answer(
        f"Шаг 2/5. Категория (одно слово, например <code>подписка</code>, <code>аренда</code>, <code>еда</code>):",
        parse_mode="HTML",
        reply_markup=_cancel_kb(),
    )


@router.message(AddRec.waiting_category)
async def _addrec_category(message: Message, state: FSMContext):
    cat = (message.text or "").strip().lower()
    if not cat or len(cat) > 40:
        await message.answer("Категория должна быть от 1 до 40 символов.", reply_markup=_cancel_kb())
        return
    await state.update_data(category=cat)
    await state.set_state(AddRec.waiting_period)
    await message.answer(
        "Шаг 3/5. Как часто списывать?",
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
        "Шаг 4/5. <b>Описание</b> (например, «Spotify») — или нажми «Пропустить»:",
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
        "Шаг 4/5. <b>Описание</b> (например, «Spotify») — или нажми «Пропустить»:",
        parse_mode="HTML",
        reply_markup=_description_kb(),
    )


@router.callback_query(F.data == "addrec_skip_desc", AddRec.waiting_description)
async def _addrec_skip_desc(callback: CallbackQuery, state: FSMContext):
    await state.update_data(description="")
    await callback.answer()
    await state.set_state(AddRec.waiting_type)
    await callback.message.answer("Шаг 5/5. Это <b>расход</b> или <b>доход</b>?", parse_mode="HTML", reply_markup=_type_kb())


@router.message(AddRec.waiting_description)
async def _addrec_description(message: Message, state: FSMContext):
    desc = (message.text or "").strip()[:200]
    await state.update_data(description=desc)
    await state.set_state(AddRec.waiting_type)
    await message.answer("Шаг 5/5. Это <b>расход</b> или <b>доход</b>?", parse_mode="HTML", reply_markup=_type_kb())


@router.callback_query(F.data.startswith("addrec_type:"), AddRec.waiting_type)
async def _addrec_type(callback: CallbackQuery, state: FSMContext):
    type_ = callback.data.split(":", 1)[1]
    data = await state.get_data()
    await state.clear()

    uid = callback.from_user.id
    first_run = datetime.now(timezone.utc) + timedelta(days=int(data["period_days"]))
    rp = storage.add_recurring_payment(
        uid,
        type_=type_,
        amount=float(data["amount"]),
        category=data["category"],
        description=data.get("description", ""),
        period_days=int(data["period_days"]),
        first_run_at=first_run,
    )
    await callback.answer()
    if not rp:
        await callback.message.answer("Не получилось создать. Попробуй ещё раз: /addrec")
        return

    kind = "доход" if type_ == "income" else "расход"
    desc = data.get("description") or "—"
    await callback.message.answer(
        f"✅ Регулярный <b>{kind}</b> создан.\n\n"
        f"Сумма: <b>{data['amount']}</b>\n"
        f"Категория: {data['category']}\n"
        f"Период: каждые {data['period_days']} дн.\n"
        f"Описание: «{desc}»\n"
        f"Первое списание: <b>{first_run.strftime('%Y-%m-%d')}</b>\n\n"
        f"Список — /myrec",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "addrec_cancel")
async def _addrec_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("Отменено")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer("Создание регулярного платежа отменено.")


@router.message(Command("delrec"))
async def cmd_delrec(message: Message):
    """Удалить регулярный платёж по id."""
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Формат: <code>/delrec &lt;id&gt;</code>. ID — из /myrec.", parse_mode="HTML")
        return
    rp_id = args[1].strip()
    ok = storage.delete_recurring_payment(message.from_user.id, rp_id)
    await message.answer("Удалено." if ok else "Не найдено. Проверь id через /myrec.")
