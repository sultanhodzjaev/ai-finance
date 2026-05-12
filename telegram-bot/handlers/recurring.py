"""Команды для управления регулярными платежами."""
import logging
import re
from datetime import datetime, timezone, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from services import plans, storage

logger = logging.getLogger(__name__)
router = Router()


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
            "Добавить: <code>/addrec &lt;сумма&gt; &lt;категория&gt; &lt;дней&gt; &lt;описание&gt;</code>\n"
            "Пример: <code>/addrec 5000 home 30 Аренда квартиры</code>\n"
            "(каждые 30 дней автоматически появится трата 5000 в категории «home»)",
            parse_mode="HTML",
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
async def cmd_addrec(message: Message):
    """
    Добавить регулярный платёж.
    Формат: /addrec <сумма> <категория> <дней> <описание> [income|expense]
    """
    text = (message.text or "").split(maxsplit=1)
    if len(text) < 2:
        await message.answer(
            "Формат: <code>/addrec &lt;сумма&gt; &lt;категория&gt; &lt;дней&gt; &lt;описание&gt; [income]</code>\n"
            "Пример: <code>/addrec 5000 home 30 Аренда квартиры</code>",
            parse_mode="HTML",
        )
        return

    rest = text[1].strip()
    type_ = "expense"
    if rest.endswith(" income"):
        type_ = "income"; rest = rest[:-len(" income")]
    elif rest.endswith(" expense"):
        rest = rest[:-len(" expense")]

    # Парсим: amount, category, days, description (description = всё остальное)
    m = re.match(r"^(\d+(?:[.,]\d+)?)\s+(\S+)\s+(\d+)\s+(.+)$", rest)
    if not m:
        await message.answer(
            "Не получилось разобрать. Формат: <code>/addrec 5000 home 30 Аренда</code>",
            parse_mode="HTML",
        )
        return

    amount = float(m.group(1).replace(",", "."))
    category = m.group(2).lower()
    period_days = int(m.group(3))
    description = m.group(4).strip()

    if period_days < 1 or period_days > 365:
        await message.answer("Период должен быть от 1 до 365 дней.")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть положительной.")
        return

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

    # Первый запуск — через period_days от сейчас
    first_run = datetime.now(timezone.utc) + timedelta(days=period_days)
    rp = storage.add_recurring_payment(
        uid,
        type_=type_,
        amount=amount,
        category=category,
        description=description,
        period_days=period_days,
        first_run_at=first_run,
    )
    if not rp:
        await message.answer("Не получилось создать. Попробуй ещё раз.")
        return

    kind = "доход" if type_ == "income" else "расход"
    await message.answer(
        f"✅ Регулярный {kind} создан.\n"
        f"Сумма: <b>{amount}</b>, категория {category}, каждые {period_days} дн.\n"
        f"Первое списание: {first_run.strftime('%Y-%m-%d')}\n"
        f"Описание: «{description}»",
        parse_mode="HTML",
    )


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
