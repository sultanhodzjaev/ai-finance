import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from services import gemini, plans, storage
from services.gemini import RateLimitError

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
        "Например: \"сколько я трачу на еду?\", "
        "\"где я слил больше всего в этом месяце?\""
    )


@router.message(AdvisorStates.waiting_question)
async def handle_advisor_question(message: Message, state: FSMContext):
    """Обрабатывает вопрос пользователя — отправляет в Gemini с контекстом трат."""
    user_id = message.from_user.id
    user = storage.get_or_create_user(
        telegram_id=user_id,
        username=message.from_user.username or "",
        first_name=message.from_user.first_name or "Друг",
    )

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
            user_question=message.text,
            currency=currency,
            transactions=transactions,
        )
    except RateLimitError:
        await thinking_msg.delete()
        await message.answer("⏳ Gemini перегружен запросами, подожди 30 секунд и попробуй снова.")
        await state.clear()
        return
    except Exception:
        await thinking_msg.delete()
        await message.answer("Что-то пошло не так с AI. Попробуй ещё раз через минуту")
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
        "📚 Команды:\n\n"
        "<b>Учёт</b>\n"
        "/today — траты за сегодня\n"
        "/stats — статистика за месяц\n"
        "/ask — спросить AI-финансиста\n\n"
        "<b>Регулярные платежи</b>\n"
        "/addrec — добавить регулярный платёж\n"
        "/myrec — список регулярных\n"
        "/delrec — удалить регулярный\n\n"
        "<b>Категории</b>\n"
        "/addcat — добавить свою категорию\n"
        "/mycats — список кастомных категорий\n"
        "/delcat — удалить категорию\n\n"
        "<b>Подписка</b>\n"
        "/plan — мой план и лимиты\n"
        "/upgrade — поднять план\n"
        "/invite — пригласить друга\n\n"
        "💡 Просто напиши трату текстом, пришли фото чека или голосовое — я сам всё распознаю.\n"
        "📥 Можно также прислать CSV-файл для импорта (Premium+).",
        parse_mode="HTML",
    )
