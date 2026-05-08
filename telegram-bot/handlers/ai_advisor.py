import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from services import gemini, storage
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
    transactions = storage.get_transactions(user_id)
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
    await message.answer(answer)


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
        "/start — главное меню\n"
        "/today — траты за сегодня\n"
        "/stats — статистика за месяц\n"
        "/ask — спросить AI-финансиста\n"
        "/help — эта справка\n\n"
        "💡 Просто напиши мне трату текстом или пришли фото чека — я сам всё распознаю!"
    )
