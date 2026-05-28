"""Команды для управления кастомными категориями (пошаговый UX)."""
import logging

from aiogram import F, Router
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


def _limit_for_user(telegram_id: int) -> int:
    user = storage.get_user(telegram_id) or {}
    plan = plans.effective_plan(user)
    return plans.LIMITS.get(plan, {}).get("categories_max", 0) or 0


class AddCat(StatesGroup):
    waiting_name = State()
    waiting_emoji = State()
    waiting_type = State()


def _cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Отмена", callback_data="addcat_cancel"),
    ]])


def _emoji_kb() -> InlineKeyboardMarkup:
    # Часто используемые эмодзи + пропустить + ввод свой
    rows = [
        [InlineKeyboardButton(text="🛒", callback_data="addcat_emoji:🛒"),
         InlineKeyboardButton(text="🍔", callback_data="addcat_emoji:🍔"),
         InlineKeyboardButton(text="🚗", callback_data="addcat_emoji:🚗"),
         InlineKeyboardButton(text="🏠", callback_data="addcat_emoji:🏠")],
        [InlineKeyboardButton(text="💊", callback_data="addcat_emoji:💊"),
         InlineKeyboardButton(text="🎬", callback_data="addcat_emoji:🎬"),
         InlineKeyboardButton(text="🎓", callback_data="addcat_emoji:🎓"),
         InlineKeyboardButton(text="🐶", callback_data="addcat_emoji:🐶")],
        [InlineKeyboardButton(text="💰", callback_data="addcat_emoji:💰"),
         InlineKeyboardButton(text="✈️", callback_data="addcat_emoji:✈️"),
         InlineKeyboardButton(text="📱", callback_data="addcat_emoji:📱"),
         InlineKeyboardButton(text="📌", callback_data="addcat_emoji:📌")],
        [InlineKeyboardButton(text="Без эмодзи", callback_data="addcat_emoji:none"),
         InlineKeyboardButton(text="Отмена",    callback_data="addcat_cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💸 Расход", callback_data="addcat_type:expense"),
        InlineKeyboardButton(text="💰 Доход",  callback_data="addcat_type:income"),
    ], [
        InlineKeyboardButton(text="Отмена", callback_data="addcat_cancel"),
    ]])


async def _send_my_categories(user_id: int, send) -> None:
    """Общая логика /mycats и callback cats_list. send — это async callable (message.answer)."""
    cats = storage.get_custom_categories(user_id)
    if not cats:
        await send(
            "У тебя пока нет своих категорий.\n\n"
            "Добавить — нажми /addcat или кнопку «➕ Добавить» в настройках.",
        )
        return

    lines = ["📚 <b>Твои категории:</b>"]
    rows = []
    for c in cats:
        tag = "доход" if c["type"] == "income" else "расход"
        lines.append(f"{c['emoji']} <b>{c['name']}</b> · {tag}")
        rows.append([InlineKeyboardButton(
            text=f"🗑 {c['emoji']} {c['name']}",
            callback_data=f"delcat:{c['id']}",
        )])
    kb = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
    await send("\n".join(lines), parse_mode="HTML", reply_markup=kb)


@router.message(Command("mycats"))
async def cmd_mycats(message: Message):
    await _send_my_categories(message.from_user.id, message.answer)


@router.callback_query(F.data == "cats_list")
async def cb_cats_list(callback: CallbackQuery):
    await _send_my_categories(callback.from_user.id, callback.message.answer)
    await callback.answer()


@router.callback_query(F.data == "cats_delete")
async def cb_cats_delete(callback: CallbackQuery):
    """То же что /delcat — список с кнопками-удалить."""
    cats = storage.get_custom_categories(callback.from_user.id)
    if not cats:
        await callback.message.answer("У тебя нет своих категорий. Добавить — кнопка «➕ Добавить».")
    else:
        rows = [[InlineKeyboardButton(
            text=f"🗑 {c['emoji']} {c['name']}",
            callback_data=f"delcat:{c['id']}",
        )] for c in cats]
        rows.append([InlineKeyboardButton(text="Отмена", callback_data="delcat_cancel")])
        await callback.message.answer(
            "Какую категорию удалить?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
    await callback.answer()


async def _start_addcat(uid: int, send, state: FSMContext) -> None:
    """Общая логика /addcat и callback cats_add."""
    cap = _limit_for_user(uid)
    have = storage.count_custom_categories(uid)
    if cap and have >= cap:
        await send(
            f"Лимит категорий исчерпан ({have}/{cap}). Подними план — /upgrade",
            parse_mode="HTML",
        )
        storage.log_event(uid, "limit_hit", {"action": "category_create", "used": have, "limit": cap})
        return

    await state.set_state(AddCat.waiting_name)
    await send(
        "📚 <b>Новая категория</b>\n\n"
        "Шаг 1/3. Как назовём? (например: <code>Корм для собаки</code>, <code>Подписки</code>)",
        parse_mode="HTML",
        reply_markup=_cancel_kb(),
    )


@router.message(Command("addcat"))
async def cmd_addcat(message: Message, state: FSMContext):
    await _start_addcat(message.from_user.id, message.answer, state)


@router.callback_query(F.data == "cats_add")
async def cb_cats_add(callback: CallbackQuery, state: FSMContext):
    await _start_addcat(callback.from_user.id, callback.message.answer, state)
    await callback.answer()


@router.message(AddCat.waiting_name)
async def _addcat_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name or len(name) > 40:
        await message.answer("Название должно быть от 1 до 40 символов.", reply_markup=_cancel_kb())
        return
    await state.update_data(name=name)
    await state.set_state(AddCat.waiting_emoji)
    await message.answer(
        "Шаг 2/3. Выбери эмодзи (можно прислать своё или нажать «Без эмодзи»):",
        reply_markup=_emoji_kb(),
    )


@router.callback_query(F.data.startswith("addcat_emoji:"), AddCat.waiting_emoji)
async def _addcat_emoji_btn(callback: CallbackQuery, state: FSMContext):
    raw = callback.data.split(":", 1)[1]
    emoji = "📌" if raw == "none" else raw
    await state.update_data(emoji=emoji)
    await callback.answer()
    await state.set_state(AddCat.waiting_type)
    await callback.message.answer("Шаг 3/3. Это <b>расход</b> или <b>доход</b>?", parse_mode="HTML", reply_markup=_type_kb())


@router.message(AddCat.waiting_emoji)
async def _addcat_emoji_text(message: Message, state: FSMContext):
    emoji = (message.text or "").strip()
    if not emoji or len(emoji) > 4:
        await message.answer("Пришли одно эмодзи или нажми кнопку.", reply_markup=_emoji_kb())
        return
    await state.update_data(emoji=emoji)
    await state.set_state(AddCat.waiting_type)
    await message.answer("Шаг 3/3. Это <b>расход</b> или <b>доход</b>?", parse_mode="HTML", reply_markup=_type_kb())


@router.callback_query(F.data.startswith("addcat_type:"), AddCat.waiting_type)
async def _addcat_type(callback: CallbackQuery, state: FSMContext):
    type_ = callback.data.split(":", 1)[1]
    data = await state.get_data()
    await state.clear()
    uid = callback.from_user.id
    cat = storage.add_custom_category(uid, data["name"], data["emoji"], type_)
    await callback.answer()
    if not cat:
        await callback.message.answer("Не удалось создать. Попробуй ещё раз: /addcat")
        return
    await callback.message.answer(
        f"✅ Создана категория {cat['emoji']} <b>{cat['name']}</b> "
        f"({'доход' if type_ == 'income' else 'расход'}).\n\n"
        f"Пока эта категория используется только в Mini App (дашборд и графики). "
        f"В чат-боте при записи трат и регулярных платежей я выбираю из основного набора.",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "addcat_cancel")
async def _addcat_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("Отменено")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer("Создание категории отменено.")


# ─── Удаление через выбор кнопкой (без id) ──────────────────────────────
@router.message(Command("delcat"))
async def cmd_delcat(message: Message):
    """Открывает список категорий с кнопками «удалить»."""
    cats = storage.get_custom_categories(message.from_user.id)
    if not cats:
        await message.answer("У тебя нет своих категорий. Добавь через /addcat.")
        return
    rows = [[InlineKeyboardButton(
        text=f"🗑 {c['emoji']} {c['name']}",
        callback_data=f"delcat:{c['id']}",
    )] for c in cats]
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="delcat_cancel")])
    await message.answer("Какую категорию удалить?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("delcat:"))
async def _delcat_click(callback: CallbackQuery):
    cat_id = callback.data.split(":", 1)[1]
    ok = storage.delete_custom_category(callback.from_user.id, cat_id)
    await callback.answer("Удалено" if ok else "Не найдена", show_alert=not ok)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer("Категория удалена ✅" if ok else "Категория не найдена.")


@router.callback_query(F.data == "delcat_cancel")
async def _delcat_cancel(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
