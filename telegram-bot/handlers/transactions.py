import logging
import uuid
from datetime import datetime

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from services import gemini, plans, storage
from services.gemini import RateLimitError
from utils.categories import (
    CATEGORIES, INCOME_CATEGORIES,
    get_category, get_category_by_id, get_category_display,
)
from utils.formatters import format_amount


def _check_action_limit(telegram_id: int, action: str) -> tuple[bool, str]:
    """
    Возвращает (allowed, deny_message). allowed=False → бот должен ответить deny_message и выйти.
    action ∈ {"transaction", "photo", "ai_question", "voice"}.
    Период считается по `plans.period_for(action)` ('day' | 'month').
    """
    user = storage.get_user(telegram_id) or {}
    plan = plans.effective_plan(user)
    limit = plans.limit_for(plan, action)
    period = plans.period_for(action)

    if action == "transaction":
        used = (
            storage.count_transactions_today(telegram_id, source="text")
            if period == "day"
            else storage.count_transactions_this_month(telegram_id, source="text")
        )
    elif action == "photo":
        used = (
            storage.count_transactions_today(telegram_id, source="photo")
            if period == "day"
            else storage.count_transactions_this_month(telegram_id, source="photo")
        )
    elif action == "ai_question":
        used = (
            storage.count_events_today(telegram_id, "ai_question")
            if period == "day"
            else storage.count_events_this_month(telegram_id, "ai_question")
        )
    elif action == "voice":
        used = (
            storage.count_transactions_today(telegram_id, source="voice")
            if period == "day"
            else storage.count_transactions_this_month(telegram_id, source="voice")
        )
    else:
        used = 0

    if limit == 0 or used >= limit:
        storage.log_event(telegram_id, "limit_hit", {"action": action, "plan": plan, "used": used, "limit": limit, "period": period})
        return False, plans.deny_message(plan, action, used, limit)

    return True, ""

logger = logging.getLogger(__name__)
router = Router()


class TransactionStates(StatesGroup):
    waiting_confirmation    = State()
    waiting_category_change = State()


def get_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Сохранить",          callback_data="confirm_save"),
        InlineKeyboardButton(text="✏️ Изменить категорию", callback_data="confirm_change_cat"),
        InlineKeyboardButton(text="❌ Отмена",             callback_data="confirm_cancel"),
    ]])


def get_categories_keyboard(tx_type: str = "expense") -> InlineKeyboardMarkup:
    """Возвращает клавиатуру категорий — расходных или доходных."""
    source = CATEGORIES if tx_type == "expense" else INCOME_CATEGORIES
    buttons = []
    for i in range(0, len(source), 2):
        row = []
        for cat in source[i:i + 2]:
            row.append(InlineKeyboardButton(
                text=f"{cat['emoji']} {cat['name']}",
                callback_data=f"cat_{cat['id']}",
            ))
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_confirmation_text(data: dict) -> str:
    """Формирует карточку подтверждения — разная для расхода и дохода."""
    currency = data.get("currency", "KGS")
    tx_type  = data.get("type", "expense")
    cat      = get_category_by_id(data["category"]) or {"emoji": "📦", "name": data["category"]}
    amount   = data["amount"]
    desc     = data.get("description") or "—"

    if tx_type == "income":
        header = "✅ Записать доход?"
        amount_str = f"+{format_amount(amount, currency)}"
    else:
        header = "💰 Записать трату?"
        amount_str = format_amount(amount, currency)

    text = (
        f"{header}\n\n"
        f"{cat['emoji']} Категория: {cat['name']}\n"
        f"💵 Сумма: {amount_str}\n"
        f"📝 Описание: {desc}"
    )
    if data.get("merchant"):
        text += f"\n🏪 Магазин: {data['merchant']}"
    text += "\n\nСохранить?"
    return text


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text_transaction(message: Message, state: FSMContext):
    """Обрабатывает текстовое сообщение как трату или доход."""
    current_state = await state.get_state()
    if current_state is not None:
        return

    user = message.from_user
    storage.get_or_create_user(
        telegram_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "Друг",
    )

    allowed, deny = _check_action_limit(user.id, "transaction")
    if not allowed:
        await message.answer(deny, parse_mode="HTML")
        return

    processing_msg = await message.answer("🤔 Обрабатываю...")

    try:
        result = await gemini.categorize_text_transaction(message.text)
    except RateLimitError:
        await processing_msg.delete()
        await message.answer("⏳ Gemini перегружен запросами, подожди 30 секунд и попробуй снова.")
        return
    except Exception:
        await processing_msg.delete()
        await message.answer("Что-то пошло не так с AI. Попробуй ещё раз через минуту")
        return

    await processing_msg.delete()

    if not result.get("success"):
        await message.answer(
            "Не понял, что ты хочешь записать. "
            "Напиши, например: «потратил 500 на обед» или «получил зарплату 50000»"
        )
        return

    db_user  = storage.get_user(user.id)
    currency = db_user.get("currency", "KGS") if db_user else "KGS"

    transaction_data = {
        "type":        result.get("type", "expense"),
        "amount":      result["amount"],
        "category":    result.get("category", "other"),
        "description": result.get("description", ""),
        "merchant":    None,
        "source":      "text",
        "currency":    currency,
    }
    await state.set_state(TransactionStates.waiting_confirmation)
    await state.update_data(transaction=transaction_data)

    await message.answer(
        build_confirmation_text(transaction_data),
        reply_markup=get_confirmation_keyboard(),
    )


@router.message(F.photo)
async def handle_photo_transaction(message: Message, state: FSMContext):
    """Обрабатывает фото как потенциальный чек (всегда расход)."""
    current_state = await state.get_state()
    if current_state is not None:
        return

    user = message.from_user
    storage.get_or_create_user(
        telegram_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "Друг",
    )

    allowed, deny = _check_action_limit(user.id, "photo")
    if not allowed:
        await message.answer(deny, parse_mode="HTML")
        return

    processing_msg = await message.answer("📷 Распознаю чек...")

    try:
        photo = message.photo[-1]
        photo_file = await message.bot.get_file(photo.file_id)
        photo_bytes_io = await message.bot.download_file(photo_file.file_path)
        photo_bytes = photo_bytes_io.read()
        result = await gemini.recognize_receipt_photo(photo_bytes)
    except RateLimitError:
        await processing_msg.delete()
        await message.answer("⏳ Gemini перегружен запросами, подожди 30 секунд и попробуй снова.")
        return
    except Exception as e:
        logger.error(f"Ошибка при обработке фото: {e}")
        await processing_msg.delete()
        await message.answer("Не получилось обработать фото. Попробуй другое или введи трату текстом")
        return

    await processing_msg.delete()

    if not result.get("success"):
        await message.answer(
            "Не получилось распознать чек. Попробуй сфотографировать ещё раз или введи трату текстом"
        )
        return

    db_user  = storage.get_user(user.id)
    currency = db_user.get("currency", "KGS") if db_user else "KGS"

    transaction_data = {
        "type":        "expense",   # чеки — всегда расходы
        "amount":      result["amount"],
        "category":    result.get("category", "other"),
        "description": result.get("description", ""),
        "merchant":    result.get("merchant"),
        "source":      "photo",
        "currency":    currency,
    }
    await state.set_state(TransactionStates.waiting_confirmation)
    await state.update_data(transaction=transaction_data)

    await message.answer(
        build_confirmation_text(transaction_data),
        reply_markup=get_confirmation_keyboard(),
    )


MAX_CSV_ROWS = 5000


@router.message(F.document)
async def handle_document_import(message: Message, state: FSMContext):
    """Импорт транзакций из CSV-файла. Доступно на планах с csv_import=True."""
    import csv as csvmod
    from io import StringIO

    current_state = await state.get_state()
    if current_state is not None:
        return

    doc = message.document
    name = (doc.file_name or "").lower()
    if not name.endswith(".csv"):
        await message.answer("Я принимаю только CSV-файлы. Если у тебя Excel — экспортируй как CSV.")
        return

    user = message.from_user
    storage.get_or_create_user(
        telegram_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "Друг",
    )

    db_user = storage.get_user(user.id) or {}
    plan = plans.effective_plan(db_user)
    if not plans.LIMITS.get(plan, {}).get("csv_import"):
        await message.answer(
            f"Импорт CSV доступен на Premium и Pro. Сейчас у тебя <b>{plans.PLAN_TITLE.get(plan, plan)}</b>.\n"
            "Подними план — /upgrade",
            parse_mode="HTML",
        )
        storage.log_event(user.id, "limit_hit", {"action": "csv_import", "plan": plan})
        return

    if doc.file_size and doc.file_size > 2 * 1024 * 1024:
        await message.answer("Файл больше 2 МБ. Раздели на части и пришли поменьше.")
        return

    processing_msg = await message.answer("📥 Читаю файл...")

    try:
        f = await message.bot.get_file(doc.file_id)
        buf = await message.bot.download_file(f.file_path)
        text = buf.read().decode("utf-8-sig", errors="replace")
    except Exception as e:
        logger.error(f"download csv: {e}")
        await processing_msg.delete()
        await message.answer("Не удалось скачать файл. Попробуй ещё раз.")
        return

    try:
        rdr = csvmod.DictReader(StringIO(text))
        rows = list(rdr)
    except Exception as e:
        logger.error(f"parse csv: {e}")
        await processing_msg.delete()
        await message.answer("Не получилось распарсить CSV. Проверь формат — должны быть колонки date, amount, category, description.")
        return

    if not rows:
        await processing_msg.delete()
        await message.answer("Файл пустой или нет заголовка.")
        return

    if len(rows) > MAX_CSV_ROWS:
        await processing_msg.delete()
        await message.answer(f"Слишком много строк ({len(rows)}). Максимум за раз — {MAX_CSV_ROWS}.")
        return

    imported = 0
    skipped = 0
    for r in rows:
        try:
            amount = float(str(r.get("amount", "")).replace(",", "."))
            if amount <= 0:
                skipped += 1; continue
            tx = {
                "type":        (r.get("type") or "expense").strip().lower(),
                "amount":      amount,
                "category":    (r.get("category") or "other").strip().lower() or "other",
                "description": (r.get("description") or "").strip()[:200],
                "merchant":    (r.get("merchant") or None) or None,
                "source":      "csv_import",
                "datetime":    (r.get("date") or "").strip() or datetime.now().isoformat(),
            }
            if tx["type"] not in ("income", "expense"):
                tx["type"] = "expense"
            storage.add_transaction(user.id, tx)
            imported += 1
        except Exception:
            skipped += 1
            continue

    await processing_msg.delete()
    storage.log_event(user.id, "csv_import", {"imported": imported, "skipped": skipped})
    await message.answer(
        f"✅ Импорт завершён.\n"
        f"Загружено: <b>{imported}</b> транзакций\n"
        f"Пропущено: <b>{skipped}</b>",
        parse_mode="HTML",
    )


@router.message(F.voice)
async def handle_voice_transaction(message: Message, state: FSMContext):
    """Транскрибирует голосовое через Gemini, парсит как обычную текстовую трату."""
    current_state = await state.get_state()
    if current_state is not None:
        return

    user = message.from_user
    storage.get_or_create_user(
        telegram_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "Друг",
    )

    allowed, deny = _check_action_limit(user.id, "voice")
    if not allowed:
        await message.answer(deny, parse_mode="HTML")
        return

    processing_msg = await message.answer("🎙 Распознаю голос...")

    try:
        voice_file = await message.bot.get_file(message.voice.file_id)
        voice_io   = await message.bot.download_file(voice_file.file_path)
        voice_bytes = voice_io.read()
        mime = message.voice.mime_type or "audio/ogg"
        transcript = await gemini.transcribe_voice(voice_bytes, mime_type=mime)
        if not transcript:
            raise RuntimeError("empty transcript")
        result = await gemini.categorize_text_transaction(transcript)
    except RateLimitError:
        await processing_msg.delete()
        await message.answer("⏳ Gemini перегружен запросами, подожди 30 секунд и попробуй снова.")
        return
    except Exception as e:
        logger.error(f"Ошибка при обработке голосового: {e}")
        await processing_msg.delete()
        await message.answer("Не получилось разобрать голосовое. Попробуй ещё раз или напиши текстом.")
        return

    await processing_msg.delete()

    if not result.get("success"):
        await message.answer(
            f"Услышал: «{transcript}», но не понял что записать.\n"
            "Скажи яснее, например: «потратил 500 на обед»."
        )
        return

    db_user  = storage.get_user(user.id)
    currency = db_user.get("currency", "KGS") if db_user else "KGS"

    transaction_data = {
        "type":        result.get("type", "expense"),
        "amount":      result["amount"],
        "category":    result.get("category", "other"),
        "description": result.get("description") or transcript[:80],
        "merchant":    None,
        "source":      "voice",
        "currency":    currency,
    }
    await state.set_state(TransactionStates.waiting_confirmation)
    await state.update_data(transaction=transaction_data)

    await message.answer(
        f"🎙 Услышал: «{transcript}»\n\n" + build_confirmation_text(transaction_data),
        reply_markup=get_confirmation_keyboard(),
    )


@router.callback_query(TransactionStates.waiting_confirmation, F.data == "confirm_save")
async def handle_save_transaction(callback: CallbackQuery, state: FSMContext):
    """Сохраняет транзакцию после подтверждения."""
    data = await state.get_data()
    td   = data["transaction"]
    tx_type = td.get("type", "expense")

    transaction = {
        "id":          str(uuid.uuid4()),
        "type":        tx_type,
        "amount":      td["amount"],
        "category":    td["category"],
        "description": td["description"],
        "merchant":    td.get("merchant"),
        "datetime":    datetime.now().isoformat(),
        "source":      td.get("source", "text"),
    }

    storage.add_transaction(callback.from_user.id, transaction)
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)

    if tx_type == "income":
        await callback.message.answer("💰 Записал доход! Поздравляю!")
    else:
        await callback.message.answer("✅ Записал трату! Так держать.")
    await callback.answer()


@router.callback_query(TransactionStates.waiting_confirmation, F.data == "confirm_change_cat")
async def handle_change_category(callback: CallbackQuery, state: FSMContext):
    """Переводит в состояние выбора категории (показывает нужный список)."""
    data    = await state.get_data()
    tx_type = data["transaction"].get("type", "expense")

    await state.set_state(TransactionStates.waiting_category_change)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Выбери категорию:",
        reply_markup=get_categories_keyboard(tx_type),
    )
    await callback.answer()


@router.callback_query(TransactionStates.waiting_confirmation, F.data == "confirm_cancel")
async def handle_cancel_transaction(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Окей, отменил.")
    await callback.answer()


@router.callback_query(TransactionStates.waiting_category_change, F.data.startswith("cat_"))
async def handle_category_selected(callback: CallbackQuery, state: FSMContext):
    """Обновляет категорию и возвращает к карточке подтверждения."""
    new_cat_id = callback.data.replace("cat_", "")
    data = await state.get_data()
    td   = data["transaction"]
    td["category"] = new_cat_id

    await state.update_data(transaction=td)
    await state.set_state(TransactionStates.waiting_confirmation)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        build_confirmation_text(td),
        reply_markup=get_confirmation_keyboard(),
    )
    await callback.answer()
