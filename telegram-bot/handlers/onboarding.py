"""Онбординг: выбор валюты, объяснение Trial, настройки."""
import logging
import os

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove, WebAppInfo,
)

from services import storage, plans

logger = logging.getLogger(__name__)
router = Router()


def _webapp_url() -> str:
    """URL Mini App — WEBAPP_URL или вычисление из REPLIT_DOMAINS."""
    explicit = os.getenv("WEBAPP_URL", "")
    if explicit:
        return explicit
    domains = os.getenv("REPLIT_DOMAINS", "")
    if domains:
        first = domains.split(",")[0].strip()
        return f"https://{first}/miniapp"
    return ""


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Глобальный выход из любого FSM-диалога. Работает даже если state пустой."""
    current = await state.get_state()
    await state.clear()
    if current:
        await message.answer("✅ Отменил. Можешь продолжать обычно.")
    else:
        await message.answer("Сейчас нет активного диалога — но ок 🙂")


# 5 валют, заявленные на старте. KGS — дефолт для legacy-юзеров.
CURRENCIES: list[tuple[str, str]] = [
    ("KGS", "🇰🇬 Сом (KGS)"),
    ("KZT", "🇰🇿 Тенге (KZT)"),
    ("RUB", "🇷🇺 Рубль (RUB)"),
    ("UZS", "🇺🇿 Сум (UZS)"),
    ("USD", "💵 Доллар (USD)"),
]
CURRENCY_CODES = {code for code, _ in CURRENCIES}


def currency_picker_kb() -> InlineKeyboardMarkup:
    """Inline-клавиатура выбора валюты — 2 колонки."""
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for code, label in CURRENCIES:
        pair.append(InlineKeyboardButton(text=label, callback_data=f"set_currency:{code}"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_inline_kb() -> InlineKeyboardMarkup:
    """Главное меню — inline-кнопки прямо под сообщением бота."""
    rows: list[list[InlineKeyboardButton]] = []
    url = _webapp_url()
    if url:
        # Mini App-кнопка на всю ширину — первая, чтобы юзер сразу видел вход в дашборд.
        rows.append([InlineKeyboardButton(text="📲 Открыть приложение", web_app=WebAppInfo(url=url))])
    rows += [
        [
            InlineKeyboardButton(text="📊 План",       callback_data="show_plan"),
            InlineKeyboardButton(text="📈 Статистика", callback_data="show_stats"),
        ],
        [
            InlineKeyboardButton(text="🤖 AI-финансист", callback_data="ask_advisor"),
            InlineKeyboardButton(text="⚙️ Настройки",    callback_data="open_settings"),
        ],
        [InlineKeyboardButton(text="🎁 Пригласить друга +7 дней Premium", callback_data="show_invite")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💱 Сменить валюту", callback_data="change_currency")],
        [InlineKeyboardButton(text="🏷 Категории",      callback_data="open_categories")],
        [InlineKeyboardButton(text="🔁 Регулярные платежи", callback_data="open_recurring")],
        [InlineKeyboardButton(text="💎 Управление подпиской", callback_data="show_subscription")],
        [InlineKeyboardButton(text="🎁 Пригласить друга", callback_data="show_invite")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="show_help")],
    ])


def categories_submenu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Мои категории", callback_data="cats_list")],
        [InlineKeyboardButton(text="➕ Добавить",       callback_data="cats_add")],
        [InlineKeyboardButton(text="🗑 Удалить",        callback_data="cats_delete")],
    ])


def recurring_submenu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Мои регулярные", callback_data="rec_list")],
        [InlineKeyboardButton(text="➕ Добавить",        callback_data="rec_add")],
        [InlineKeyboardButton(text="🗑 Удалить",         callback_data="rec_delete")],
    ])


async def _send_trial_intro(message_or_query, currency: str, first_name: str) -> None:
    """Шлёт интро после выбора валюты — объясняет Trial и подталкивает к первой трате.
    Для Owner-юзеров (allowlist) лимиты Trial бессмысленны — упоминаем безлимит вместо них."""
    user_id = message_or_query.from_user.id if isinstance(message_or_query, CallbackQuery) else message_or_query.from_user.id
    user = storage.get_user(user_id) or {}
    plan = plans.effective_plan(user)

    intro_currency = (
        f"💱 Валюта: <b>{currency}</b>. Все траты теперь будут считаться в ней "
        f"(поменять — ⚙️ Настройки).\n\n"
    )

    if plan == plans.PLAN_OWNER:
        body = "👑 <b>У тебя Owner-доступ</b> — безлимит ко всем функциям бота.\n\n"
    else:
        trial_cfg = plans.LIMITS[plans.PLAN_TRIAL]
        body = (
            f"🎁 <b>У тебя 7 дней бесплатного Trial</b>\n"
            f"  • {trial_cfg['transactions_per_day']} трат в день\n"
            f"  • {trial_cfg['ai_questions_per_month']} вопросов AI-финансисту / мес\n"
            f"  • {trial_cfg['photo_per_month']} фото чеков / мес\n"
            f"  • {trial_cfg['voice_per_month']} голосовых / мес\n"
            f"  • Импорт CSV: {'да' if trial_cfg['csv_import'] else 'нет'}\n\n"
        )

    text = intro_currency + body + (
        f"<b>Попробуй прямо сейчас 👇</b>\n"
        f"Напиши обычным сообщением, например:\n"
        f"  • <code>250 кофе</code>\n"
        f"  • <code>потратил 1500 на такси</code>\n"
        f"  • <code>зарплата 50000</code>\n\n"
        f"Я сам определю сумму, категорию и сохраню."
    )
    if isinstance(message_or_query, CallbackQuery):
        await message_or_query.message.answer(text, parse_mode="HTML", reply_markup=main_inline_kb())
    else:
        await message_or_query.answer(text, parse_mode="HTML", reply_markup=main_inline_kb())


@router.callback_query(F.data.startswith("set_currency:"))
async def cb_set_currency(callback: CallbackQuery, state: FSMContext):
    code = callback.data.split(":", 1)[1]
    if code not in CURRENCY_CODES:
        await callback.answer("Неизвестная валюта", show_alert=True)
        return
    await state.clear()  # выходим из чужого FSM, если юзер кликнул из state.
    storage.update_user_currency(callback.from_user.id, code)
    storage.log_event(callback.from_user.id, "currency_set", {"currency": code})

    user = storage.get_user(callback.from_user.id) or {}
    # Trial-интро шлём ТОЛЬКО при первом выборе после /start. После log_event выше
    # текущий currency_set уже учтён — поэтому == 1 = это и есть первая установка.
    is_first_setup = (
        storage.count_transactions_this_month(callback.from_user.id) == 0
        and storage.count_events_this_month(callback.from_user.id, "currency_set") <= 1
    )

    if is_first_setup:
        await _send_trial_intro(callback, code, user.get("first_name") or "Друг")
    else:
        await callback.message.answer(
            f"💱 Валюта обновлена: <b>{code}</b>.\n"
            f"Все новые траты будут в этой валюте. Старые записи не пересчитываются.",
            parse_mode="HTML",
            reply_markup=main_inline_kb(),
        )
    await callback.answer()


# ---------------------------------------------------------------------------
# /settings и кнопка «⚙️ Настройки»
# ---------------------------------------------------------------------------

def _settings_text(user: dict) -> str:
    currency = user.get("currency") or "—"
    plan = plans.effective_plan(user)
    plan_title = plans.PLAN_TITLE.get(plan, plan)
    return (
        f"⚙️ <b>Настройки</b>\n\n"
        f"💱 Валюта: <b>{currency}</b>\n"
        f"📋 План: <b>{plan_title}</b>\n"
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    user = storage.get_user(message.from_user.id) or {}
    await message.answer(_settings_text(user), parse_mode="HTML", reply_markup=settings_kb())


@router.callback_query(F.data == "open_settings")
async def cb_open_settings(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = storage.get_user(callback.from_user.id) or {}
    await callback.message.answer(_settings_text(user), parse_mode="HTML", reply_markup=settings_kb())
    await callback.answer()


@router.callback_query(F.data == "show_plan")
async def cb_show_plan(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    from handlers.plan import build_plan_text, _upgrade_keyboard
    from services import plans, storage
    text = build_plan_text(callback.from_user.id)
    if text is None:
        await callback.message.answer("Сначала нажми /start — я тебя ещё не вижу в базе.")
    else:
        # Inline-кнопки апгрейда — те же что в cmd_plan/legacy_plan,
        # чтобы юзеру было одинаково независимо от точки входа.
        user = storage.get_user(callback.from_user.id) or {}
        current_plan = plans.effective_plan(user)
        kb = None
        if current_plan in (plans.PLAN_TRIAL, plans.PLAN_FREE, plans.PLAN_PREMIUM):
            kb = _upgrade_keyboard(current_plan)
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "change_currency")
async def cb_change_currency(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        "💱 Выбери новую валюту:",
        reply_markup=currency_picker_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "open_categories")
async def cb_open_categories(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        "🏷 <b>Категории</b>\n\n"
        "Здесь можно завести свои категории — пока они показываются в Mini App "
        "(дашборд и графики). В чат-боте при записи трат я по-прежнему выбираю из "
        "основного набора.",
        parse_mode="HTML",
        reply_markup=categories_submenu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "open_recurring")
async def cb_open_recurring(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        "🔁 <b>Регулярные платежи</b>\n\n"
        "Списания, которые повторяются — подписки, аренда, зарплата. Я сам создаю "
        "транзакцию когда подходит дата.",
        parse_mode="HTML",
        reply_markup=recurring_submenu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "show_subscription")
async def cb_show_subscription(callback: CallbackQuery, state: FSMContext):
    """Показывает текущий план + кнопки апгрейда (если юзер не на платном тарифе)."""
    await state.clear()
    from handlers.plan import build_plan_text, _upgrade_keyboard
    text = build_plan_text(callback.from_user.id)
    if text is None:
        await callback.message.answer("Сначала нажми /start.")
        await callback.answer()
        return

    user = storage.get_user(callback.from_user.id) or {}
    plan = plans.effective_plan(user)
    # Кнопки апгрейда показываем всем кроме Pro и Owner (тем некуда расти).
    if plan in (plans.PLAN_FREE, plans.PLAN_TRIAL, plans.PLAN_PREMIUM):
        await callback.message.answer(text, parse_mode="HTML", reply_markup=_upgrade_keyboard())
    else:
        await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


# ---------------------------------------------------------------------------
# Legacy reply-keyboard fallback: если юзер всё ещё видит старую persistent-клаву
# (текст «📊 План» / «📈 Статистика» / «🤖 AI-финансист» / «⚙️ Настройки»),
# обрабатываем нажатие и одновременно стираем legacy-клавиатуру.
# Можно удалить через 1-2 недели когда у всех старая клава пропадёт.
# ---------------------------------------------------------------------------

@router.message(F.text == "📊 План")
async def legacy_plan(message: Message):
    # Не дублируем логику cmd_plan — он сам добавит inline-кнопки апгрейда
    # по текущему тарифу. ReplyKeyboardRemove не делаем тут специально: иначе
    # пришлось бы два сообщения подряд (Telegram не даёт смешать reply-keyboard
    # с inline в одном). Старая клава сотрётся при следующем legacy-нажатии.
    from handlers.plan import cmd_plan
    await cmd_plan(message)


@router.message(F.text == "📈 Статистика")
async def legacy_stats(message: Message):
    from handlers.stats import cmd_stats
    # ReplyKeyboardRemove() сотрётся при следующих legacy-нажатиях (📊/⚙️/🤖) — здесь
    # пропускаем, чтобы не плодить два сообщения подряд (cmd_stats сам шлёт заголовок).
    await cmd_stats(message)


@router.message(F.text == "🤖 AI-финансист")
async def legacy_ai(message: Message):
    await message.answer(
        "🤖 Спроси меня о своих финансах. Например: «где я слил больше всего за неделю?»",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(F.text == "⚙️ Настройки")
async def legacy_settings(message: Message):
    user = storage.get_user(message.from_user.id) or {}
    await message.answer(_settings_text(user), parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    await message.answer("Что меняем 👇", reply_markup=settings_kb())
