"""Алёрты по бюджетам категорий.

После каждого сохранения расхода — проверяем потрачено vs лимит на категории
у юзера и шлём пуш на 80% и 100% порогах. Идемпотентность по месяцу через
events таблицу: один пуш на порог в пределах календарного месяца.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from services import storage
from utils.categories import get_category_by_id
from utils.formatters import format_amount

logger = logging.getLogger(__name__)


async def maybe_alert_budget(bot, telegram_id: int, category: str) -> None:
    """Проверяет бюджет на category после сохранения новой траты юзера.
    Если потрачено перевалило 80% или 100% месячного лимита и алёрт ещё не
    отправлен в этом месяце — шлёт пуш и логирует event для идемпотентности.
    Шлёт максимум один пуш на вызов (100% важнее 80%)."""
    if bot is None:
        return
    try:
        budget = storage.get_budget(telegram_id, category)
    except Exception as e:
        logger.warning("maybe_alert_budget get_budget(%s, %s): %s", telegram_id, category, e)
        return
    if not budget:
        return
    try:
        limit = float(budget["monthly_limit"])
    except (TypeError, ValueError):
        return
    if limit <= 0:
        return

    spent = storage.sum_category_expense_this_month(telegram_id, category)
    pct = (spent / limit) * 100
    month_key = datetime.now(timezone.utc).strftime("%Y-%m")
    currency = budget.get("currency", "KGS")
    cat_meta = get_category_by_id(category) or {"emoji": "📦", "name": category}

    # 100% важнее 80%: проверяем сверху вниз, шлём максимум один.
    for threshold_pct, threshold_id in [(100, "100"), (80, "80")]:
        if pct < threshold_pct:
            continue
        if storage.has_budget_alert_sent(telegram_id, category, month_key, threshold_id):
            continue
        if threshold_pct == 100:
            text = (
                f"🔴 <b>Бюджет {cat_meta['emoji']} {cat_meta['name']} превышен</b>\n\n"
                f"Потрачено в этом месяце: <b>{format_amount(spent, currency)}</b>\n"
                f"Лимит: <b>{format_amount(limit, currency)}</b> ({round(pct)}%)\n\n"
                f"Можно посмотреть/изменить — Mini App → Бюджеты."
            )
        else:
            text = (
                f"🟡 <b>Бюджет {cat_meta['emoji']} {cat_meta['name']} — 80% израсходовано</b>\n\n"
                f"Потрачено: <b>{format_amount(spent, currency)}</b> из <b>{format_amount(limit, currency)}</b>\n"
                f"Осталось: <b>{format_amount(max(limit - spent, 0), currency)}</b> до конца месяца."
            )
        try:
            await bot.send_message(telegram_id, text, parse_mode="HTML")
        except Exception as e:
            logger.warning("budget alert send failed tg=%s: %s", telegram_id, e)
        # Логируем даже при ошибке отправки — чтобы при ретрае не было дублей
        storage.log_event(telegram_id, f"budget_alert_{threshold_id}", {
            "category": category, "month": month_key,
            "spent":    spent, "limit": limit,
        })
        return
