"""Подписки, лимиты и проверка прав."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Literal

logger = logging.getLogger(__name__)

PLAN_TRIAL   = "trial"
PLAN_FREE    = "free"
PLAN_BASIC   = "basic"
PLAN_PREMIUM = "premium"

Action = Literal["transaction", "photo", "ai_question"]

# Лимиты в день. 0 = не разрешено вовсе.
LIMITS: dict[str, dict[str, int]] = {
    PLAN_TRIAL:   {"transaction": 100, "photo": 30, "ai_question": 30},
    PLAN_FREE:    {"transaction": 5,   "photo": 0,  "ai_question": 3},
    PLAN_BASIC:   {"transaction": 100, "photo": 5,  "ai_question": 0},
    PLAN_PREMIUM: {"transaction": 200, "photo": 30, "ai_question": 30},
}

# Цены в Telegram Stars
PRICE_STARS = {
    PLAN_BASIC:   100,   # $2
    PLAN_PREMIUM: 250,   # $5
}

PLAN_TITLE = {
    PLAN_TRIAL:   "Trial",
    PLAN_FREE:    "Free",
    PLAN_BASIC:   "Базовый",
    PLAN_PREMIUM: "Премиум",
}


def _parse_ts(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        # Supabase возвращает ISO-строку (например "2026-05-19T10:11:12.345+00:00")
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        logger.warning("plans._parse_ts: не удалось распарсить %r", value)
        return None


def effective_plan(user: dict) -> str:
    """
    Возвращает фактический план с учётом срока действия.
    - trial → free, если trial_until прошёл
    - basic/premium → free, если subscription_until прошёл (null = бессрочно)
    """
    now = datetime.now(timezone.utc)
    plan = (user or {}).get("plan") or PLAN_TRIAL

    if plan == PLAN_TRIAL:
        trial_until = _parse_ts(user.get("trial_until"))
        if trial_until and trial_until > now:
            return PLAN_TRIAL
        return PLAN_FREE

    if plan in (PLAN_BASIC, PLAN_PREMIUM):
        sub_until = _parse_ts(user.get("subscription_until"))
        if sub_until is None:
            return plan  # бессрочно (для владельца)
        if sub_until > now:
            return plan
        return PLAN_FREE

    return PLAN_FREE


def limit_for(plan: str, action: Action) -> int:
    return LIMITS.get(plan, LIMITS[PLAN_FREE]).get(action, 0)


def _upgrade_hint(plan: str, action: Action) -> str:
    if action == "ai_question":
        return "AI-финансист доступен только в Премиум-плане — /upgrade"
    if plan == PLAN_FREE:
        return "Купи подписку, чтобы снять лимиты — /upgrade"
    return "Лимиты обновятся завтра, либо подними план — /upgrade"


def deny_message(plan: str, action: Action, used: int, limit: int) -> str:
    """Текст, который бот покажет юзеру при превышении лимита."""
    plan_title = PLAN_TITLE.get(plan, plan)
    if limit == 0:
        if action == "photo":
            head = "📷 Фото чеков недоступны в твоём текущем плане."
        elif action == "ai_question":
            head = "🤖 AI-финансист недоступен в твоём текущем плане."
        else:
            head = "Это действие недоступно в твоём текущем плане."
        return f"{head}\nТекущий план: <b>{plan_title}</b>.\n\n{_upgrade_hint(plan, action)}"

    if action == "transaction":
        head = f"Ты записал {used} трат сегодня — это лимит плана <b>{plan_title}</b>."
    elif action == "photo":
        head = f"Ты отправил {used} фото чеков сегодня — лимит плана <b>{plan_title}</b>."
    elif action == "ai_question":
        head = f"Ты задал {used} вопросов финансисту сегодня — лимит плана <b>{plan_title}</b>."
    else:
        head = "Лимит на сегодня исчерпан."

    return f"{head}\n\n{_upgrade_hint(plan, action)}"
