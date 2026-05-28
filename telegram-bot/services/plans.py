"""Подписки, лимиты и проверка прав.

Финальная тарифная таблица — см. `wiki/topics/finance-bots/ai-finansist-unit-economics-and-tariffs-v1.md`.
Все runtime-проверки опираются на эту таблицу. Параметры, для которых ещё нет соответствующей
функциональности в продукте (голос, импорт CSV, экспорт, регулярные платежи, кол-во категорий),
зафиксированы декларативно и будут подключаться по мере появления.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Literal

logger = logging.getLogger(__name__)

PLAN_TRIAL   = "trial"
PLAN_FREE    = "free"
PLAN_PREMIUM = "premium"
PLAN_OWNER = "owner"

# Юзеры с безлимитным доступом. Username приходит без @.
OWNER_USERNAMES: set[str] = {"sultanhodzjaevv", "aidar_ed"}
OWNER_TELEGRAM_IDS: set[int] = {5557488294}
PLAN_PRO     = "pro"

# Действия с runtime-проверкой лимита. Остальные параметры декларативны.
Action = Literal["transaction", "photo", "ai_question", "voice"]

# Финальная тарифная таблица (2026-05-12).
LIMITS: dict[str, dict] = {
    PLAN_TRIAL: {
        "transactions_per_day":    14,
        "ai_questions_per_month":  100,
        "voice_per_month":         50,
        "photo_per_month":         30,
        "history_days":            None,         # вся за период триала
        "categories_max":          15,
        "recurring_payments_max":  5,
        "csv_import":              False,
        "exports_total":           1,            # 1 разовая выгрузка за весь триал
        "mini_app_analytics":      "full",
    },
    PLAN_FREE: {
        "transactions_per_day":    2,
        "ai_questions_per_month":  10,
        "voice_per_month":         0,
        "photo_per_month":         0,
        "history_days":            30,
        "categories_max":          5,
        "recurring_payments_max":  1,
        "csv_import":              False,
        "exports_per_month":       0,
        "mini_app_analytics":      "basic",
    },
    PLAN_PREMIUM: {
        "transactions_per_day":    17,
        "ai_questions_per_month":  300,
        "voice_per_month":         60,
        "photo_per_month":         30,
        "history_days":            365,
        "categories_max":          30,
        "recurring_payments_max":  10,
        "csv_import":              True,
        "exports_per_month":       3,
        "mini_app_analytics":      "full",
    },
    PLAN_PRO: {
        "transactions_per_day":    100,
        "ai_questions_per_month":  1500,
        "voice_per_month":         200,
        "photo_per_month":         150,
        "history_days":            730,
        "categories_max":          100,
        "recurring_payments_max":  50,
        "csv_import":              True,
        "exports_per_month":       10,
        "mini_app_analytics":      "full",
    },
    PLAN_OWNER: {
        # Безлимит для владельца/допущенных юзеров: 1_000_000 ≈ ∞ для практики.
        "transactions_per_day":    1_000_000,
        "ai_questions_per_month":  1_000_000,
        "voice_per_month":         1_000_000,
        "photo_per_month":         1_000_000,
        "history_days":            None,            # вся история
        "categories_max":          1_000_000,
        "recurring_payments_max":  1_000_000,
        "csv_import":              True,
        "exports_per_month":       1_000_000,
        "mini_app_analytics":      "full",
    },
}

PRICE_USD = {
    PLAN_PREMIUM: 5,
    PLAN_PRO:     10,
}

# Lava.top offerId для каждого тарифа. Создано в кабинете Лавы как SUBSCRIPTION/MONTHLY.
LAVA_OFFER_IDS = {
    PLAN_PREMIUM: "df63e9a8-c8e3-4fc4-aaca-43b380e1d6fe",
    PLAN_PRO:     "e48623e7-746d-4780-b28c-1759dc5b8559",
}

# Маппинг суммы в USD → тариф для разбора webhook'ов от Лавы.
# Webhook не несёт offerId, но несёт amount; так дешевле и надёжнее, чем сравнивать сторонние title.
USD_TO_PLAN = {
    5:  PLAN_PREMIUM,
    10: PLAN_PRO,
}

PLAN_TITLE = {
    PLAN_TRIAL:   "Trial",
    PLAN_FREE:    "Free",
    PLAN_PREMIUM: "Premium",
    PLAN_PRO:     "Pro",
    PLAN_OWNER:   "Owner",
}

# Какой ключ в LIMITS соответствует каждому action и какой период мерим.
ACTION_TO_LIMIT = {
    "transaction": ("transactions_per_day",    "day"),
    "photo":       ("photo_per_month",         "month"),
    "ai_question": ("ai_questions_per_month",  "month"),
    "voice":       ("voice_per_month",         "month"),
}


def _parse_ts(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        logger.warning("plans._parse_ts: не удалось распарсить %r", value)
        return None


def effective_plan(user: dict) -> str:
    """
    Возвращает фактический план с учётом срока действия:
    - trial → free, если trial_until прошёл
    - premium/pro → free, если subscription_until прошёл (null = бессрочно)
    - owner-allowlist (username/telegram_id) — всегда PLAN_OWNER (безлимит)
    """
    now = datetime.now(timezone.utc)
    u = user or {}
    uname = (u.get("username") or "").lstrip("@").lower()
    tg_id = u.get("telegram_id")
    if uname in OWNER_USERNAMES or tg_id in OWNER_TELEGRAM_IDS:
        return PLAN_OWNER
    plan = u.get("plan") or PLAN_TRIAL

    if plan == PLAN_TRIAL:
        trial_until = _parse_ts(u.get("trial_until"))
        if trial_until and trial_until > now:
            return PLAN_TRIAL
        return PLAN_FREE

    if plan in (PLAN_PREMIUM, PLAN_PRO):
        sub_until = _parse_ts(u.get("subscription_until"))
        if sub_until is None:
            return plan  # бессрочно
        if sub_until > now:
            return plan
        return PLAN_FREE

    return PLAN_FREE


def limit_for(plan: str, action: Action) -> int:
    """Числовой лимит для пары (plan, action). 0 — действие запрещено в плане."""
    key, _period = ACTION_TO_LIMIT.get(action, (None, None))
    if key is None:
        return 0
    return LIMITS.get(plan, LIMITS[PLAN_FREE]).get(key, 0) or 0


def period_for(action: Action) -> str:
    """'day' | 'month' — за какой период считается лимит."""
    _key, period = ACTION_TO_LIMIT.get(action, (None, "day"))
    return period


def _upgrade_hint(plan: str, action: Action) -> str:
    if plan == PLAN_FREE:
        return "Купи Premium или Pro, чтобы снять лимит — /upgrade"
    if plan == PLAN_TRIAL:
        return "До конца триала действуют ограниченные лимиты. После — можно купить Premium или Pro — /upgrade"
    return "Лимит обновится со следующим периодом, либо подними план — /upgrade"


def format_limits_summary(plan: str) -> str:
    """Краткая HTML-сводка лимитов плана — для пушового сообщения об активации/продлении подписки."""
    cfg = LIMITS.get(plan)
    if not cfg:
        return ""
    history_line = (
        "вся история" if cfg.get("history_days") is None
        else f"{cfg['history_days']} дней истории"
    )
    return (
        f"  • {cfg['transactions_per_day']} трат в день\n"
        f"  • {cfg['ai_questions_per_month']} вопросов AI-финансисту в месяц\n"
        f"  • {cfg['photo_per_month']} фото чеков в месяц\n"
        f"  • {cfg['voice_per_month']} голосовых в месяц\n"
        f"  • {history_line}, {cfg['categories_max']} категорий\n"
        f"  • Импорт CSV и экспорт ({cfg.get('exports_per_month', 0)}/мес)"
    )


def deny_message(plan: str, action: Action, used: int, limit: int) -> str:
    """Текст, который бот покажет юзеру при превышении лимита."""
    plan_title = PLAN_TITLE.get(plan, plan)
    period = period_for(action)
    period_word = "сегодня" if period == "day" else "в этом месяце"

    if limit == 0:
        head_map = {
            "photo":       "📷 Фото чеков недоступны в твоём текущем плане.",
            "ai_question": "🤖 AI-финансист недоступен в твоём текущем плане.",
            "voice":       "🎙 Голосовые сообщения недоступны в твоём текущем плане.",
            "transaction": "Это действие недоступно в твоём текущем плане.",
        }
        head = head_map.get(action, "Это действие недоступно.")
        return f"{head}\nТекущий план: <b>{plan_title}</b>.\n\n{_upgrade_hint(plan, action)}"

    head_map = {
        "transaction": f"Ты записал {used} трат {period_word} — это лимит плана <b>{plan_title}</b>.",
        "photo":       f"Ты отправил {used} фото чеков {period_word} — лимит плана <b>{plan_title}</b>.",
        "ai_question": f"Ты задал {used} вопросов финансисту {period_word} — лимит плана <b>{plan_title}</b>.",
        "voice":       f"Ты записал {used} голосовых {period_word} — лимит плана <b>{plan_title}</b>.",
    }
    head = head_map.get(action, f"Лимит на {period_word} исчерпан.")
    return f"{head}\n\n{_upgrade_hint(plan, action)}"
