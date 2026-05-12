"""Команды для управления кастомными категориями."""
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from services import plans, storage

logger = logging.getLogger(__name__)
router = Router()


def _limit_for_user(telegram_id: int) -> int:
    user = storage.get_user(telegram_id) or {}
    plan = plans.effective_plan(user)
    return plans.LIMITS.get(plan, {}).get("categories_max", 0) or 0


@router.message(Command("mycats"))
async def cmd_mycats(message: Message):
    """Список кастомных категорий пользователя."""
    cats = storage.get_custom_categories(message.from_user.id)
    if not cats:
        await message.answer(
            "У тебя пока нет кастомных категорий.\n\n"
            "Добавь свою: <code>/addcat &lt;эмодзи&gt; &lt;название&gt; [income]</code>\n"
            "Пример: <code>/addcat 🐶 Корм для собаки</code>",
            parse_mode="HTML",
        )
        return
    lines = ["📚 <b>Твои кастомные категории:</b>\n"]
    for c in cats:
        tag = "доход" if c["type"] == "income" else "расход"
        lines.append(f"{c['emoji']} <b>{c['name']}</b> · {tag}\n  <code>/delcat {c['id']}</code>")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("addcat"))
async def cmd_addcat(message: Message):
    """
    Создаёт кастомную категорию.
    Формат: /addcat <эмодзи> <название> [income|expense]
    """
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Формат: <code>/addcat &lt;эмодзи&gt; &lt;название&gt; [income]</code>\n"
            "Пример: <code>/addcat 🐶 Корм для собаки</code>\n"
            "Если нужно сделать категорию дохода — добавь <code>income</code> в конце.",
            parse_mode="HTML",
        )
        return

    rest = args[1].strip()
    # Последнее слово может быть type
    tokens = rest.rsplit(maxsplit=1)
    type_ = "expense"
    if len(tokens) == 2 and tokens[1].lower() in ("income", "expense"):
        type_ = tokens[1].lower()
        rest  = tokens[0].strip()

    # Первый «токен» — эмодзи (может быть 1-2 символа), остальное — название
    parts = rest.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Не вижу эмодзи и название. Пример: <code>/addcat 🐶 Корм для собаки</code>",
            parse_mode="HTML",
        )
        return
    emoji, name = parts[0], parts[1]

    # Проверка лимита
    uid = message.from_user.id
    cap = _limit_for_user(uid)
    have = storage.count_custom_categories(uid)
    if cap and have >= cap:
        await message.answer(
            f"Лимит категорий исчерпан ({have}/{cap}). Подними план — /upgrade",
            parse_mode="HTML",
        )
        storage.log_event(uid, "limit_hit", {"action": "category_create", "used": have, "limit": cap})
        return

    cat = storage.add_custom_category(uid, name, emoji, type_)
    if not cat:
        await message.answer("Не удалось создать категорию. Попробуй ещё раз.")
        return

    await message.answer(
        f"✅ Создана категория {cat['emoji']} <b>{cat['name']}</b> ({'доход' if type_ == 'income' else 'расход'}).\n\n"
        f"Чтобы использовать — выбирай её в Mini App при подтверждении.",
        parse_mode="HTML",
    )


@router.message(Command("delcat"))
async def cmd_delcat(message: Message):
    """Удаляет кастомную категорию: /delcat <uuid>."""
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Формат: <code>/delcat &lt;id&gt;</code>\n"
            "ID можно увидеть в /mycats.",
            parse_mode="HTML",
        )
        return
    cat_id = args[1].strip()
    ok = storage.delete_custom_category(message.from_user.id, cat_id)
    if ok:
        await message.answer("Категория удалена.")
    else:
        await message.answer("Категория не найдена. Проверь id через /mycats.")
