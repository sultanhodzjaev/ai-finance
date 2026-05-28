import asyncio
import logging
import uuid
from collections import defaultdict
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
    # waiting_confirmation теперь multi-card: state.data["cards"] = {card_id: tx_data}.
    # Карточек может быть несколько одновременно (юзер кидает 5 чеков подряд —
    # каждая обрабатывается независимо по своему card_id).
    waiting_confirmation          = State()
    waiting_batch_confirmation    = State()
    waiting_batch_category_change = State()


def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    """Простой плюрализатор: 1 трата / 2 траты / 5 трат."""
    n10 = abs(n) % 10
    n100 = abs(n) % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14):
        return few
    return many


# ---------------------------------------------------------------------------
# Multi-card модель: несколько pending-карточек одновременно
# ---------------------------------------------------------------------------

# Per-user lock на чтение-модификацию-запись state.data["cards"]. Без него при
# одновременной отправке нескольких фото/сообщений их хендлеры читают одинаковый
# снапшот cards={...} и каждый пишет своё — последняя запись затирает остальные
# (именно так пользователи сталкивались с «4 карточки слились в одну»).
_USER_STATE_LOCKS: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def _new_card_id() -> str:
    """Короткий ID (8 hex символов), чтобы влезть в 64-байтный лимит callback_data."""
    return uuid.uuid4().hex[:8]


def get_confirmation_keyboard(card_id: str) -> InlineKeyboardMarkup:
    """Кнопки карточки. card_id зашит в callback_data — каждая карточка независима."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Сохранить",          callback_data=f"cs:{card_id}"),
        InlineKeyboardButton(text="✏️ Изменить категорию", callback_data=f"cg:{card_id}"),
        InlineKeyboardButton(text="❌ Отмена",             callback_data=f"cc:{card_id}"),
    ]])


def get_card_categories_keyboard(tx_type: str, card_id: str) -> InlineKeyboardMarkup:
    """Категории для конкретной single-card карточки — id зашит в callback_data.
    Отдельная от батч-флоу (тот использует cat_<cat_id> без card_id)."""
    source = CATEGORIES if tx_type == "expense" else INCOME_CATEGORIES
    buttons = []
    for i in range(0, len(source), 2):
        row = []
        for cat in source[i:i + 2]:
            row.append(InlineKeyboardButton(
                text=f"{cat['emoji']} {cat['name']}",
                callback_data=f"cat:{card_id}:{cat['id']}",
            ))
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_categories_keyboard(tx_type: str = "expense") -> InlineKeyboardMarkup:
    """Категории для батч-флоу — callback_data = cat_<cat_id> без card_id.
    Сохранена как есть для совместимости с handle_batch_edit/handle_batch_category_selected."""
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


async def _add_card(state: FSMContext, user_id: int, td: dict) -> str:
    """Кладёт карточку в state.data["cards"] под новым card_id, выставляет
    waiting_confirmation. Возвращает card_id. RMW защищён per-user lock'ом."""
    async with _USER_STATE_LOCKS[user_id]:
        card_id = _new_card_id()
        data = await state.get_data()
        cards = data.get("cards") or {}
        cards[card_id] = td
        await state.set_state(TransactionStates.waiting_confirmation)
        await state.update_data(cards=cards)
        return card_id


async def _remove_card(state: FSMContext, user_id: int, card_id: str) -> int:
    """Убирает карточку из state.data["cards"]. Если карточек больше нет — чистит state.
    Возвращает количество оставшихся pending карточек."""
    async with _USER_STATE_LOCKS[user_id]:
        data = await state.get_data()
        cards = data.get("cards") or {}
        cards.pop(card_id, None)
        if not cards:
            # Полностью очищаем state — иначе stale batch-ключи могут мешать.
            await state.clear()
            return 0
        await state.update_data(cards=cards)
        return len(cards)


async def _update_card(state: FSMContext, user_id: int, card_id: str, patch: dict) -> dict | None:
    """Применяет patch к карточке. Возвращает обновлённую td или None если её уже нет."""
    async with _USER_STATE_LOCKS[user_id]:
        data = await state.get_data()
        cards = data.get("cards") or {}
        td = cards.get(card_id)
        if td is None:
            return None
        td.update(patch)
        cards[card_id] = td
        await state.update_data(cards=cards)
        return td


def _can_add_new_card(current_state: str | None) -> bool:
    """Разрешено ли в текущем стейте добавить новую single-card карточку.
    Разрешаем только когда state пустой или уже waiting_confirmation (multi-card),
    блокируем во всех остальных диалогах (batch, регулярные платежи, онбординг и т.д.)."""
    if current_state is None:
        return True
    return current_state == TransactionStates.waiting_confirmation.state


# ---------------------------------------------------------------------------
# Batch-флоу: карточка для нескольких операций из одного голосового
# ---------------------------------------------------------------------------

def build_batch_text(items: list, currency: str, transcript: str) -> str:
    """Карточка для нескольких операций из одного голосового."""
    n = len(items)
    word = _plural_ru(n, "операцию", "операции", "операций")
    lines = [
        f"🎙 Услышал: «{transcript}»",
        "",
        f"<b>Нашёл {n} {word}:</b>",
        "",
    ]
    total_expense = 0.0
    total_income  = 0.0
    for i, it in enumerate(items, 1):
        cat = get_category_by_id(it["category"]) or {"emoji": "📦", "name": it["category"]}
        amt = format_amount(it["amount"], currency)
        desc = it.get("description") or "—"
        sign = "+" if it["type"] == "income" else ""
        lines.append(f"{i}. {cat['emoji']} {cat['name']} — <b>{sign}{amt}</b> · {desc}")
        if it["type"] == "income":
            total_income += it["amount"]
        else:
            total_expense += it["amount"]

    summary = []
    if total_expense:
        summary.append(f"💸 расход <b>{format_amount(total_expense, currency)}</b>")
    if total_income:
        summary.append(f"💰 доход <b>{format_amount(total_income, currency)}</b>")
    if summary:
        lines += ["", "Итого: " + " · ".join(summary)]
    return "\n".join(lines)


def get_batch_keyboard(n: int) -> InlineKeyboardMarkup:
    """Клавиатура батч-подтверждения. Save All сверху, далее по строке edit/delete."""
    rows = [[InlineKeyboardButton(text="✅ Сохранить все", callback_data="batch_save_all")]]
    # Кнопки edit и delete — по 4 в ряд максимум, чтобы умещались на узком экране.
    chunk = 4
    for off in range(0, n, chunk):
        edit_row = [
            InlineKeyboardButton(text=f"✏️ {i+1}", callback_data=f"batch_edit_{i}")
            for i in range(off, min(off + chunk, n))
        ]
        rows.append(edit_row)
    for off in range(0, n, chunk):
        del_row = [
            InlineKeyboardButton(text=f"🗑 {i+1}", callback_data=f"batch_delete_{i}")
            for i in range(off, min(off + chunk, n))
        ]
        rows.append(del_row)
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="batch_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
    from utils.safety import sanitize_input, detect_injection
    current_state = await state.get_state()
    if not _can_add_new_card(current_state):
        await message.answer(
            "⚠️ У тебя сейчас открыт другой диалог (например /addrec или /ask). "
            "Заверши его или нажми /cancel — потом я смогу записать твою трату."
        )
        return

    user = message.from_user
    storage.get_or_create_user(
        telegram_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "Друг",
    )

    # Защита от prompt injection и cost runaway: длина + keyword-фильтр.
    clean_text, truncated = sanitize_input(message.text or "", kind="transaction")
    if truncated:
        await message.answer(
            "Сообщение слишком длинное (>300 символов). Опиши трату короче, "
            "например «250 кофе» или «потратил 1500 на такси»."
        )
        return
    if (matched := detect_injection(clean_text)):
        storage.log_event(user.id, "suspicious_input", {"kind": "transaction", "matched": matched[:80]})
        await message.answer(
            "Похоже, в сообщении инструкции для AI, а не описание траты. "
            "Напиши обычным языком — например, «250 кофе»."
        )
        return

    allowed, deny = _check_action_limit(user.id, "transaction")
    if not allowed:
        await message.answer(deny, parse_mode="HTML")
        return

    processing_msg = await message.answer("🤔 Обрабатываю...")

    try:
        result = await gemini.categorize_text_transaction(clean_text)
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
    card_id = await _add_card(state, user.id, transaction_data)

    await message.answer(
        build_confirmation_text(transaction_data),
        reply_markup=get_confirmation_keyboard(card_id),
    )


@router.message(F.photo)
async def handle_photo_transaction(message: Message, state: FSMContext):
    """Обрабатывает фото как потенциальный чек (всегда расход)."""
    current_state = await state.get_state()
    if not _can_add_new_card(current_state):
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
    card_id = await _add_card(state, user.id, transaction_data)

    await message.answer(
        build_confirmation_text(transaction_data),
        reply_markup=get_confirmation_keyboard(card_id),
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

    user = message.from_user
    storage.get_or_create_user(
        telegram_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "Друг",
    )

    # Сначала проверяем план — если CSV-импорт недоступен, бесполезно мучить юзера
    # требованием «пришли в CSV». Free-юзер с .xlsx должен видеть «не на твоём тарифе»,
    # а не «принимаю только CSV».
    db_user = storage.get_user(user.id) or {}
    plan = plans.effective_plan(db_user)
    if not plans.LIMITS.get(plan, {}).get("csv_import"):
        await message.answer(
            f"Импорт файлов доступен на Premium и Pro. Сейчас у тебя <b>{plans.PLAN_TITLE.get(plan, plan)}</b>.\n"
            "Подними план — /upgrade",
            parse_mode="HTML",
        )
        storage.log_event(user.id, "limit_hit", {"action": "csv_import", "plan": plan})
        return

    doc = message.document
    name = (doc.file_name or "").lower()
    if not name.endswith(".csv"):
        await message.answer("Я принимаю только CSV-файлы. Если у тебя Excel — экспортируй как CSV.")
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
    logger.info(f"voice handler: tg_user={message.from_user.id} duration={message.voice.duration if message.voice else '?'}s "
                f"mime={message.voice.mime_type if message.voice else '?'}")
    current_state = await state.get_state()
    # Голос с одной операцией = single-card (пускаем поверх pending карточек);
    # с несколькими операциями = batch (батч требует эксклюзивный стейт, не уживается
    # с pending single-cards — это проверим уже после парсинга).
    if not _can_add_new_card(current_state):
        logger.info(f"voice handler: skipped, user in FSM state {current_state}")
        return

    user = message.from_user
    storage.get_or_create_user(
        telegram_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "Друг",
    )

    allowed, deny = _check_action_limit(user.id, "voice")
    if not allowed:
        logger.info(f"voice handler: limit hit for {user.id}")
        await message.answer(deny, parse_mode="HTML")
        return

    processing_msg = await message.answer("🎙 Распознаю голос...")

    try:
        voice_file = await message.bot.get_file(message.voice.file_id)
        voice_io   = await message.bot.download_file(voice_file.file_path)
        voice_bytes = voice_io.read()
        mime = message.voice.mime_type or "audio/ogg"
        logger.info(f"voice handler: downloaded {len(voice_bytes)} bytes, mime={mime}, calling Gemini")
        transcript = await gemini.transcribe_voice(voice_bytes, mime_type=mime)
        logger.info(f"voice handler: transcript={transcript[:80]!r}")
        if not transcript:
            raise RuntimeError("empty transcript")
        # Парсим как batch — даже одиночная трата приходит как items=[1]; так не
        # дублируем логику и единственно меняется UX при n>1.
        result = await gemini.categorize_text_transactions_batch(transcript)
        logger.info(f"voice handler: categorized success={result.get('success')} n={len(result.get('items') or [])}")
    except RateLimitError:
        await processing_msg.delete()
        await message.answer("⏳ Gemini перегружен запросами, подожди 30 секунд и попробуй снова.")
        return
    except Exception as e:
        logger.exception(f"voice handler: error during processing: {e}")
        await processing_msg.delete()
        await message.answer(f"Не получилось разобрать голосовое: {e}\nПопробуй ещё раз или напиши текстом.")
        return

    await processing_msg.delete()

    if not result.get("success"):
        await message.answer(
            f"Услышал: «{transcript}», но не понял что записать.\n"
            "Скажи яснее, например: «потратил 500 на обед»."
        )
        return

    items: list = result["items"]

    db_user  = storage.get_user(user.id)
    currency = db_user.get("currency", "KGS") if db_user else "KGS"

    # Trim до оставшейся квоты голосового. Limit-check в начале проверяет «есть
    # ли вообще квота» (used < limit), но не знает n. Если в голосе 3 операции,
    # а осталось 2 — режем до 2 и предупреждаем юзера, чтобы не перерасходовать.
    plan = plans.effective_plan(db_user or {})
    voice_limit = plans.limit_for(plan, "voice")
    used_voice = storage.count_transactions_this_month(user.id, source="voice")
    remaining = max(voice_limit - used_voice, 0)
    trimmed = 0
    if remaining and remaining < len(items):
        trimmed = len(items) - remaining
        items = items[:remaining]

    # === Одиночная операция: добавляем как обычную single-card ===
    if len(items) == 1:
        it = items[0]
        transaction_data = {
            "type":        it["type"],
            "amount":      it["amount"],
            "category":    it["category"],
            "description": it["description"] or transcript[:80],
            "merchant":    None,
            "source":      "voice",
            "currency":    currency,
        }
        card_id = await _add_card(state, user.id, transaction_data)

        # Одноразовая подсказка про батч-голос: транскрипт длинный (юзер явно
        # пробовал говорить много), но Gemini увидел только 1 операцию —
        # вероятно, он не знает, что так можно. Показываем ровно один раз.
        hint = ""
        if len(transcript) >= 60 and not storage.has_event_ever(user.id, "voice_batch_hint_shown"):
            hint = (
                "\n\n💡 <i>Можно говорить несколько трат подряд в одном голосовом — например, "
                "«такси 500, обед 2000, кино 800» — я разнесу по категориям.</i>"
            )
            storage.log_event(user.id, "voice_batch_hint_shown", {"transcript_len": len(transcript)})

        await message.answer(
            f"🎙 Услышал: «{transcript}»\n\n" + build_confirmation_text(transaction_data) + hint,
            reply_markup=get_confirmation_keyboard(card_id),
            parse_mode="HTML",
        )
        return

    # === Несколько операций: batch-карточка ===
    # Batch требует эксклюзивный стейт. Если у юзера уже есть pending single-cards,
    # попросить сначала разобраться с ними, иначе батч их затрёт/перепутает.
    existing_data = await state.get_data()
    if existing_data.get("cards"):
        await message.answer(
            "⚠️ У тебя есть несохранённые карточки выше — подтверди или отмени их, "
            "потом наговори голосовое с несколькими тратами ещё раз."
        )
        return

    await state.set_state(TransactionStates.waiting_batch_confirmation)
    await state.update_data(
        batch_items=items,
        batch_transcript=transcript,
        batch_trimmed=trimmed,
    )

    text = build_batch_text(items, currency, transcript)
    if trimmed:
        word = _plural_ru(trimmed, "операция", "операции", "операций")
        text += (
            f"\n\n⚠️ Не поместилось ещё {trimmed} {word} — в этом месяце "
            f"осталось {remaining} голосовых на тарифе <b>{plans.PLAN_TITLE.get(plan, plan)}</b>."
        )

    await message.answer(
        text,
        reply_markup=get_batch_keyboard(len(items)),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Single-card callback-хендлеры (multi-card aware): cs:/cg:/cc:/cat:
# ---------------------------------------------------------------------------


async def _expire_stale_card(callback: CallbackQuery, message_text: str = "") -> None:
    """Карточка уже не в state.data — кнопка устарела (рестарт бота, отмена и т.п.).
    Снимаем клавиатуру, показываем спиннер-ответ."""
    try:
        if message_text:
            await callback.message.edit_text(message_text, reply_markup=None)
        else:
            await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer("Эта карточка уже неактуальна, начни заново")


@router.callback_query(TransactionStates.waiting_confirmation, F.data.startswith("cs:"))
async def handle_card_save(callback: CallbackQuery, state: FSMContext):
    """Сохраняет одну конкретную карточку (по card_id из callback_data)."""
    card_id = callback.data[3:]
    data = await state.get_data()
    cards = data.get("cards") or {}
    td = cards.get(card_id)
    if td is None:
        await _expire_stale_card(callback)
        return

    tx_type = td.get("type", "expense")
    transaction = {
        "id":          str(uuid.uuid4()),
        "type":        tx_type,
        "amount":      td["amount"],
        "category":    td["category"],
        "description": td.get("description", ""),
        "merchant":    td.get("merchant"),
        "datetime":    datetime.now().isoformat(),
        "source":      td.get("source", "text"),
    }
    storage.add_transaction(callback.from_user.id, transaction)
    if tx_type == "expense":
        from services.budgets import maybe_alert_budget
        await maybe_alert_budget(callback.message.bot, callback.from_user.id, td["category"])
    await _remove_card(state, callback.from_user.id, card_id)

    currency = td.get("currency", "KGS")
    amt_str = format_amount(td["amount"], currency)
    desc = td.get("description") or td.get("merchant") or ("доход" if tx_type == "income" else "трата")
    if tx_type == "income":
        confirm_text = f"💰 Записал доход: <b>+{amt_str}</b> ({desc}). Поздравляю!"
    else:
        confirm_text = f"✅ Записал трату: <b>{amt_str}</b> ({desc}). Так держать."
    try:
        await callback.message.edit_text(confirm_text, parse_mode="HTML")
    except Exception:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(confirm_text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(TransactionStates.waiting_confirmation, F.data.startswith("cg:"))
async def handle_card_change_category(callback: CallbackQuery, state: FSMContext):
    """Показывает список категорий для конкретной карточки. card_id остаётся
    в callback_data кнопок — поэтому новый стейт не нужен."""
    card_id = callback.data[3:]
    data = await state.get_data()
    cards = data.get("cards") or {}
    td = cards.get(card_id)
    if td is None:
        await _expire_stale_card(callback)
        return

    tx_type = td.get("type", "expense")
    try:
        await callback.message.edit_text(
            "Выбери категорию:",
            reply_markup=get_card_categories_keyboard(tx_type, card_id),
        )
    except Exception:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            "Выбери категорию:",
            reply_markup=get_card_categories_keyboard(tx_type, card_id),
        )
    await callback.answer()


@router.callback_query(TransactionStates.waiting_confirmation, F.data.startswith("cc:"))
async def handle_card_cancel(callback: CallbackQuery, state: FSMContext):
    """Отменяет одну конкретную карточку."""
    card_id = callback.data[3:]
    data = await state.get_data()
    cards = data.get("cards") or {}
    if card_id not in cards:
        await _expire_stale_card(callback)
        return
    await _remove_card(state, callback.from_user.id, card_id)
    try:
        await callback.message.edit_text("❌ Запись отменена.", reply_markup=None)
    except Exception:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer("Окей, отменил.")
    await callback.answer()


@router.callback_query(TransactionStates.waiting_confirmation, F.data.startswith("cat:"))
async def handle_card_category_selected(callback: CallbackQuery, state: FSMContext):
    """Выбрана категория для конкретной карточки — обновляем и возвращаем карточку
    с обычными кнопками подтверждения."""
    parts = callback.data.split(":", 2)
    if len(parts) != 3:
        await callback.answer("Не понял")
        return
    _, card_id, new_cat_id = parts

    td = await _update_card(state, callback.from_user.id, card_id, {"category": new_cat_id})
    if td is None:
        await _expire_stale_card(callback)
        return

    try:
        await callback.message.edit_text(
            build_confirmation_text(td),
            reply_markup=get_confirmation_keyboard(card_id),
        )
    except Exception:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            build_confirmation_text(td),
            reply_markup=get_confirmation_keyboard(card_id),
        )
    await callback.answer()


# ---------------------------------------------------------------------------
# Batch-подтверждение (несколько операций из одного голосового)
# ---------------------------------------------------------------------------


@router.callback_query(TransactionStates.waiting_batch_confirmation, F.data == "batch_save_all")
async def handle_batch_save_all(callback: CallbackQuery, state: FSMContext):
    """Сохраняет все оставшиеся в батче операции одной транзакцией каждая."""
    data = await state.get_data()
    items: list = data.get("batch_items") or []
    if not items:
        await state.clear()
        await callback.message.edit_text("❌ Нечего сохранять.")
        await callback.answer()
        return

    saved = 0
    alerted_categories: set[str] = set()  # один пуш на категорию даже если в батче несколько трат туда
    for it in items:
        try:
            storage.add_transaction(callback.from_user.id, {
                "id":          str(uuid.uuid4()),
                "type":        it.get("type", "expense"),
                "amount":      it["amount"],
                "category":    it.get("category", "other"),
                "description": it.get("description", ""),
                "merchant":    None,
                "datetime":    datetime.now().isoformat(),
                "source":      "voice",
            })
            saved += 1
            if it.get("type", "expense") == "expense":
                cat = it.get("category", "other")
                if cat not in alerted_categories:
                    alerted_categories.add(cat)
                    from services.budgets import maybe_alert_budget
                    await maybe_alert_budget(callback.message.bot, callback.from_user.id, cat)
        except Exception as e:
            logger.error(f"batch save: tx failed: {e}")

    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    word = _plural_ru(saved, "операцию", "операции", "операций")
    await callback.message.answer(f"✅ Записал {saved} {word}! Так держать.")
    await callback.answer()


@router.callback_query(TransactionStates.waiting_batch_confirmation, F.data.startswith("batch_delete_"))
async def handle_batch_delete(callback: CallbackQuery, state: FSMContext):
    """Удаляет одну операцию из батча. Если остаётся 1 — переключаемся на single-card."""
    try:
        idx = int(callback.data.replace("batch_delete_", ""))
    except ValueError:
        await callback.answer("Не понял индекс")
        return

    data = await state.get_data()
    items: list = data.get("batch_items") or []
    transcript: str = data.get("batch_transcript") or ""
    if not (0 <= idx < len(items)):
        await callback.answer("Эта позиция уже не существует")
        return

    items.pop(idx)

    if not items:
        await state.clear()
        try:
            await callback.message.edit_text("❌ Удалил все позиции — нечего сохранять.")
        except Exception:
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer("Окей, отменил.")
        await callback.answer()
        return

    db_user = storage.get_user(callback.from_user.id) or {}
    currency = db_user.get("currency", "KGS")

    if len(items) == 1:
        # Остался один — превращаем в single-card и чистим батч-стейт.
        # _add_card сам выставит waiting_confirmation; перед этим очищаем
        # batch-ключи, чтобы не висели в state.
        it = items[0]
        td = {
            "type":        it.get("type", "expense"),
            "amount":      it["amount"],
            "category":    it.get("category", "other"),
            "description": it.get("description") or transcript[:80],
            "merchant":    None,
            "source":      "voice",
            "currency":    currency,
        }
        await state.update_data(batch_items=None, batch_transcript=None, batch_trimmed=None, batch_edit_idx=None)
        card_id = await _add_card(state, callback.from_user.id, td)
        try:
            await callback.message.edit_text(
                f"🎙 Услышал: «{transcript}»\n\n" + build_confirmation_text(td),
                reply_markup=get_confirmation_keyboard(card_id),
            )
        except Exception:
            await callback.message.answer(
                build_confirmation_text(td),
                reply_markup=get_confirmation_keyboard(card_id),
            )
        await callback.answer("Удалил")
        return

    await state.update_data(batch_items=items)
    text = build_batch_text(items, currency, transcript)
    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_batch_keyboard(len(items)),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            text,
            reply_markup=get_batch_keyboard(len(items)),
            parse_mode="HTML",
        )
    await callback.answer("Удалил")


@router.callback_query(TransactionStates.waiting_batch_confirmation, F.data.startswith("batch_edit_"))
async def handle_batch_edit(callback: CallbackQuery, state: FSMContext):
    """Открывает выбор категории для конкретной операции из батча."""
    try:
        idx = int(callback.data.replace("batch_edit_", ""))
    except ValueError:
        await callback.answer("Не понял индекс")
        return

    data = await state.get_data()
    items: list = data.get("batch_items") or []
    if not (0 <= idx < len(items)):
        await callback.answer("Эта позиция уже не существует")
        return

    tx_type = items[idx].get("type", "expense")
    await state.set_state(TransactionStates.waiting_batch_category_change)
    await state.update_data(batch_edit_idx=idx)

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        f"Выбери категорию для позиции <b>{idx + 1}</b>:",
        reply_markup=get_categories_keyboard(tx_type),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(TransactionStates.waiting_batch_category_change, F.data.startswith("cat_"))
async def handle_batch_category_selected(callback: CallbackQuery, state: FSMContext):
    """После выбора категории — возвращаем юзера к батч-карточке."""
    new_cat_id = callback.data.replace("cat_", "")
    data = await state.get_data()
    items: list = data.get("batch_items") or []
    transcript: str = data.get("batch_transcript") or ""
    idx = data.get("batch_edit_idx")
    if idx is None or not (0 <= idx < len(items)):
        await callback.answer("Позиция потерялась")
        return

    items[idx]["category"] = new_cat_id
    await state.update_data(batch_items=items, batch_edit_idx=None)
    await state.set_state(TransactionStates.waiting_batch_confirmation)

    db_user = storage.get_user(callback.from_user.id) or {}
    currency = db_user.get("currency", "KGS")
    text = build_batch_text(items, currency, transcript)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        text,
        reply_markup=get_batch_keyboard(len(items)),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(TransactionStates.waiting_batch_confirmation, F.data == "batch_cancel")
async def handle_batch_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.edit_text("❌ Запись отменена.", reply_markup=None)
    except Exception:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer("Окей, отменил.")
    await callback.answer()


# ---------------------------------------------------------------------------
# Совместимость со старыми кнопками (до multi-card refactor'а)
# ---------------------------------------------------------------------------
# Кнопки confirm_save/confirm_change_cat/confirm_cancel могли остаться у юзера
# в чате с прошлых сессий бота (Redis-стейт мы не чистим). Чтобы они не выглядели
# «глухими», ловим их и говорим юзеру отправить заново.

@router.callback_query(F.data.in_({"confirm_save", "confirm_change_cat", "confirm_cancel"}))
async def handle_legacy_confirm_buttons(callback: CallbackQuery, state: FSMContext):
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer("Эта карточка устарела, отправь заново", show_alert=True)
