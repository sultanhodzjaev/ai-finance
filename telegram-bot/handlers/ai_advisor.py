import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from services import gemini, plans, storage
from services.gemini import RateLimitError


def _advisor_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Отмена", callback_data="advisor_cancel"),
    ]])

logger = logging.getLogger(__name__)
router = Router()


class AdvisorStates(StatesGroup):
    """FSM-состояния для диалога с AI-финансистом."""
    waiting_question = State()  # Ожидаем вопрос от пользователя


@router.message(Command("ask"))
@router.callback_query(F.data == "ask_advisor")
async def cmd_ask(event: Message | CallbackQuery, state: FSMContext):
    """Запускает диалог с AI-финансистом — переходит в режим ожидания вопроса."""
    if isinstance(event, CallbackQuery):
        send = event.message.answer
        await event.answer()
    else:
        send = event.answer

    await state.set_state(AdvisorStates.waiting_question)
    await send(
        "Задай мне любой вопрос про твои финансы. "
        "Например: «сколько я трачу на еду?», «где я слил больше всего в этом месяце?»\n\n"
        "Чтобы выйти из диалога — /cancel или кнопка ниже.",
        reply_markup=_advisor_cancel_kb(),
    )


@router.callback_query(F.data == "advisor_cancel")
async def cb_advisor_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("Отменено")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer("Окей, отменил.")


@router.message(AdvisorStates.waiting_question)
async def handle_advisor_question(message: Message, state: FSMContext):
    """Обрабатывает вопрос пользователя — отправляет в Gemini с контекстом трат."""
    from utils.safety import sanitize_input, detect_injection
    user_id = message.from_user.id
    user = storage.get_or_create_user(
        telegram_id=user_id,
        username=message.from_user.username or "",
        first_name=message.from_user.first_name or "Друг",
    )

    # Защита: длина + keyword-фильтр до проверки лимитов и до похода в Gemini.
    # Так не тратим квоту юзера на мусорный/вредный запрос.
    clean_text, truncated = sanitize_input(message.text or "", kind="advisor")
    if truncated:
        await message.answer(
            "Вопрос слишком длинный (>500 символов). Сформулируй короче — "
            "я отвечу точнее, если вопрос конкретный.",
            reply_markup=_advisor_cancel_kb(),
        )
        return  # state не очищаем — юзер может переформулировать
    if (matched := detect_injection(clean_text)):
        storage.log_event(user_id, "suspicious_input", {"kind": "advisor", "matched": matched[:80]})
        await message.answer(
            "Я — финансовый помощник и могу отвечать только на вопросы про твои деньги. "
            "Спроси что-то про свои траты или доходы.",
            reply_markup=_advisor_cancel_kb(),
        )
        return

    plan = plans.effective_plan(user)
    limit = plans.limit_for(plan, "ai_question")
    period = plans.period_for("ai_question")
    used = (
        storage.count_events_today(user_id, "ai_question")
        if period == "day"
        else storage.count_events_this_month(user_id, "ai_question")
    )
    if limit == 0 or used >= limit:
        storage.log_event(user_id, "limit_hit", {"action": "ai_question", "plan": plan, "used": used, "limit": limit, "period": period})
        await message.answer(plans.deny_message(plan, "ai_question", used, limit), parse_mode="HTML")
        await state.clear()
        return

    history_days = plans.LIMITS.get(plan, {}).get("history_days")
    transactions = storage.get_transactions(user_id, since_days=history_days)
    currency = user.get("currency", "KGS")

    thinking_msg = await message.answer("🤔 Анализирую твои финансы...")

    try:
        answer = await gemini.ask_financial_advisor(
            user_question=clean_text,
            currency=currency,
            transactions=transactions,
        )
    except RateLimitError:
        await thinking_msg.delete()
        await message.answer("⏳ Gemini перегружен запросами, подожди 30 секунд и попробуй снова.")
        await state.clear()
        return
    except Exception as e:
        # Раньше catch проглатывал ошибку без следа — теперь оставляем traceback,
        # чтобы понимать что упало (timeout/5xx/safety filter/etc).
        logger.exception("ask_financial_advisor failed for user=%s question=%r: %s",
                         user_id, clean_text[:120], e)
        await thinking_msg.delete()
        await message.answer(
            "Не получилось ответить — Gemini не отозвался или прислал ошибку. "
            "Попробуй переформулировать вопрос или повтори через минуту."
        )
        await state.clear()
        return

    await thinking_msg.delete()
    await state.clear()
    storage.log_event(user_id, "ai_question", {"plan": plan, "length": len(message.text or "")})

    # Gemini иногда оборачивает ответ в ```html``` или ```. Снимаем.
    cleaned = answer.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0].rstrip()

    try:
        await message.answer(cleaned, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        # Если HTML невалидный (например, незакрытый тег) — фолбэк plain text
        logger.warning(f"HTML parse failed for advisor reply: {e}; falling back to plain text")
        await message.answer(cleaned, disable_web_page_preview=True)


@router.message(Command("help"))
@router.callback_query(F.data == "show_help")
async def cmd_help(event: Message | CallbackQuery):
    """Показывает справку по командам бота."""
    if isinstance(event, CallbackQuery):
        send = event.message.answer
        await event.answer()
    else:
        send = event.answer

    await send(
        "💡 <b>Как пользоваться</b>\n\n"
        "Чтобы записать трату — просто напиши обычным сообщением:\n"
        "  • «250 кофе»\n"
        "  • «потратил 1500 на такси»\n"
        "  • «зарплата 50000»\n\n"
        "Я разберу сумму, категорию и сохраню.\n\n"
        "📷 Пришли <b>фото чека</b> — распознаю и запишу.\n"
        "🎙 Пришли <b>голосовое</b> — распознаю и запишу.\n"
        "📥 Пришли <b>CSV-файл</b> — импортирую транзакции (Premium и Pro).\n\n"
        "<b>Где что лежит:</b>\n"
        "  • 📲 «Открыть приложение» — Mini App с графиками\n"
        "  • 📈 «Статистика» — итоги за день/неделю/месяц\n"
        "  • 🤖 «AI-финансист» — ответит на вопрос про твои деньги\n"
        "  • ⚙️ «Настройки» — валюта, категории, регулярные платежи,\n"
        "    подписка, пригласить друга\n\n"
        "Главное меню всегда под сообщением /start. Если открыт диалог "
        "(например, добавление регулярного платежа) — выйти можно кнопкой "
        "«Отмена» или /cancel.",
        parse_mode="HTML",
    )
