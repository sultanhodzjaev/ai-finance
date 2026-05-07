import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from services import gemini, storage
from utils.categories import CATEGORIES, get_category, get_category_display
from utils.formatters import format_amount

logger = logging.getLogger(__name__)
router = Router()


class TransactionStates(StatesGroup):
    """FSM-состояния для процесса записи транзакции."""
    waiting_confirmation = State()    # Ожидаем подтверждения (✅/✏️/❌)
    waiting_category_change = State()  # Ожидаем выбора новой категории


def get_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Кнопки подтверждения транзакции."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Сохранить", callback_data="confirm_save"),
            InlineKeyboardButton(text="✏️ Изменить категорию", callback_data="confirm_change_cat"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="confirm_cancel"),
        ]
    ])


def get_categories_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для выбора категории — 2 кнопки в ряд."""
    buttons = []
    for i in range(0, len(CATEGORIES), 2):
        row = []
        for cat in CATEGORIES[i:i + 2]:
            row.append(InlineKeyboardButton(
                text=f"{cat['emoji']} {cat['name']}",
                callback_data=f"cat_{cat['id']}",
            ))
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_confirmation_text(data: dict) -> str:
    """Формирует текст карточки подтверждения транзакции."""
    currency = data.get("currency", "KGS")
    cat = get_category(data["category"])
    amount_str = format_amount(data["amount"], currency)

    text = (
        "💰 Записать трату?\n\n"
        f"{cat['emoji']} Категория: {cat['name']}\n"
        f"💵 Сумма: {amount_str}\n"
        f"📝 Описание: {data.get('description') or '—'}"
    )
    # Для фото-чеков добавляем название магазина
    if data.get("merchant"):
        text += f"\n🏪 Магазин: {data['merchant']}"
    text += "\n\nСохранить?"
    return text


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text_transaction(message: Message, state: FSMContext):
    """
    Обрабатывает любое текстовое сообщение (не команду) как потенциальную трату.
    Если пользователь уже в другом FSM-состоянии — пропускает.
    """
    current_state = await state.get_state()
    if current_state is not None:
        return  # Другой хэндлер обработает это сообщение

    # Регистрируем пользователя если нужно
    user = message.from_user
    storage.get_or_create_user(
        telegram_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "Друг",
    )

    processing_msg = await message.answer("🤔 Обрабатываю...")

    try:
        result = await gemini.categorize_text_transaction(message.text)
    except Exception:
        await processing_msg.delete()
        await message.answer("Что-то пошло не так с AI. Попробуй ещё раз через минуту")
        return

    await processing_msg.delete()

    if not result.get("success"):
        await message.answer(
            "Не понял, что ты хочешь записать. "
            "Напиши, например: \"потратил 500 на обед\""
        )
        return

    # Получаем валюту пользователя
    db_user = storage.get_user(user.id)
    currency = db_user.get("currency", "KGS") if db_user else "KGS"

    # Сохраняем данные во FSM-state до получения подтверждения
    transaction_data = {
        "amount": result["amount"],
        "category": result.get("category", "other"),
        "description": result.get("description", ""),
        "merchant": None,
        "source": "text",
        "currency": currency,
    }
    await state.set_state(TransactionStates.waiting_confirmation)
    await state.update_data(transaction=transaction_data)

    await message.answer(
        build_confirmation_text(transaction_data),
        reply_markup=get_confirmation_keyboard(),
    )


@router.message(F.photo)
async def handle_photo_transaction(message: Message, state: FSMContext):
    """Обрабатывает фото как потенциальный чек."""
    current_state = await state.get_state()
    if current_state is not None:
        return

    user = message.from_user
    storage.get_or_create_user(
        telegram_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "Друг",
    )

    processing_msg = await message.answer("📷 Распознаю чек...")

    try:
        # Берём фото наилучшего качества (последнее в списке)
        photo = message.photo[-1]
        photo_file = await message.bot.get_file(photo.file_id)
        photo_bytes_io = await message.bot.download_file(photo_file.file_path)
        photo_bytes = photo_bytes_io.read()

        result = await gemini.recognize_receipt_photo(photo_bytes)
    except Exception as e:
        logger.error(f"Ошибка при обработке фото: {e}")
        await processing_msg.delete()
        await message.answer(
            "Не получилось обработать фото. "
            "Попробуй другое или введи трату текстом"
        )
        return

    await processing_msg.delete()

    if not result.get("success"):
        await message.answer(
            "Не получилось распознать чек. "
            "Попробуй сфотографировать ещё раз или введи трату текстом"
        )
        return

    db_user = storage.get_user(user.id)
    currency = db_user.get("currency", "KGS") if db_user else "KGS"

    transaction_data = {
        "amount": result["amount"],
        "category": result.get("category", "other"),
        "description": result.get("description", ""),
        "merchant": result.get("merchant"),
        "source": "photo",
        "currency": currency,
    }
    await state.set_state(TransactionStates.waiting_confirmation)
    await state.update_data(transaction=transaction_data)

    await message.answer(
        build_confirmation_text(transaction_data),
        reply_markup=get_confirmation_keyboard(),
    )


@router.callback_query(TransactionStates.waiting_confirmation, F.data == "confirm_save")
async def handle_save_transaction(callback: CallbackQuery, state: FSMContext):
    """Сохраняет транзакцию в память после подтверждения пользователем."""
    data = await state.get_data()
    transaction_data = data["transaction"]

    # Финальная транзакция в формате хранилища
    transaction = {
        "amount": transaction_data["amount"],
        "category": transaction_data["category"],
        "description": transaction_data["description"],
        "merchant": transaction_data.get("merchant"),
        "datetime": datetime.now().isoformat(),
        "source": transaction_data.get("source", "text"),
    }

    storage.add_transaction(callback.from_user.id, transaction)
    await state.clear()

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("✅ Записал! Так держать.")
    await callback.answer()


@router.callback_query(TransactionStates.waiting_confirmation, F.data == "confirm_change_cat")
async def handle_change_category(callback: CallbackQuery, state: FSMContext):
    """Переводит в состояние выбора новой категории."""
    await state.set_state(TransactionStates.waiting_category_change)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Выбери категорию:",
        reply_markup=get_categories_keyboard(),
    )
    await callback.answer()


@router.callback_query(TransactionStates.waiting_confirmation, F.data == "confirm_cancel")
async def handle_cancel_transaction(callback: CallbackQuery, state: FSMContext):
    """Отменяет запись транзакции."""
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Окей, отменил.")
    await callback.answer()


@router.callback_query(TransactionStates.waiting_category_change, F.data.startswith("cat_"))
async def handle_category_selected(callback: CallbackQuery, state: FSMContext):
    """Обновляет категорию и возвращает к карточке подтверждения."""
    new_category_id = callback.data.replace("cat_", "")

    data = await state.get_data()
    transaction_data = data["transaction"]
    transaction_data["category"] = new_category_id
    await state.update_data(transaction=transaction_data)
    await state.set_state(TransactionStates.waiting_confirmation)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        build_confirmation_text(transaction_data),
        reply_markup=get_confirmation_keyboard(),
    )
    await callback.answer()
