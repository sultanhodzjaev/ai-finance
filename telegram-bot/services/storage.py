"""
Хранилище данных на Supabase (PostgreSQL).
Таблицы создаются автоматически при первом запуске через init_db().
"""
import logging
import os
import uuid
from datetime import datetime, timezone
from functools import lru_cache

from supabase import create_client, Client

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _client() -> Client:
    url = os.environ["SUPABASE_URL"]
    # service_role ключ обходит RLS — используем для серверного приложения
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_KEY"]
    return create_client(url, key)


# ---------------------------------------------------------------------------
# Инициализация схемы БД
# ---------------------------------------------------------------------------

def init_db() -> None:
    """
    Создаёт таблицы если их нет.
    Вызывается один раз при старте приложения.
    """
    sb = _client()
    # Проверяем наличие таблиц попыткой SELECT — если таблицы нет, поймаем ошибку
    try:
        sb.table("users").select("telegram_id").limit(1).execute()
        sb.table("transactions").select("id").limit(1).execute()
        logger.info("Supabase: таблицы уже существуют")
    except Exception:
        # Таблицы нужно создать через Supabase SQL editor или RPC
        # Здесь логируем, реальное создание — через SQL ниже
        logger.warning(
            "Supabase: таблицы не найдены — создай их через SQL Editor в Supabase Dashboard. "
            "SQL-скрипт находится в telegram-bot/supabase_schema.sql"
        )


# ---------------------------------------------------------------------------
# Пользователи
# ---------------------------------------------------------------------------

def get_user(telegram_id: int) -> dict | None:
    """Возвращает пользователя по Telegram ID или None."""
    try:
        res = _client().table("users").select("*").eq("telegram_id", telegram_id).maybe_single().execute()
        return res.data
    except Exception as e:
        logger.error(f"get_user({telegram_id}): {e}")
        return None


def create_user(telegram_id: int, username: str, first_name: str) -> dict:
    """Создаёт нового пользователя. currency='KGS' — дефолт из схемы; онбординг сразу спросит у юзера и поменяет."""
    user = {
        "telegram_id": telegram_id,
        "username":    username,
        "first_name":  first_name,
        "currency":    "KGS",
    }
    try:
        res = _client().table("users").insert(user).execute()
        return res.data[0]
    except Exception as e:
        logger.error(f"create_user({telegram_id}): {e}")
        return {**user, "telegram_id": telegram_id}


def update_user_currency(telegram_id: int, currency: str) -> None:
    """Сохраняет выбранную юзером валюту. Старые транзакции не пересчитываются."""
    try:
        _client().table("users").update({"currency": currency}).eq("telegram_id", telegram_id).execute()
    except Exception as e:
        logger.error(f"update_user_currency({telegram_id}, {currency}): {e}")


def get_or_create_user(telegram_id: int, username: str, first_name: str) -> dict:
    """Возвращает существующего пользователя или создаёт нового."""
    user = get_user(telegram_id)
    if user is None:
        user = create_user(telegram_id, username, first_name)
    return user


def get_or_create_user_with_flag(telegram_id: int, username: str, first_name: str) -> tuple[dict, bool]:
    """Как get_or_create_user, но второй кортеж — True если юзер только что создан."""
    user = get_user(telegram_id)
    if user is None:
        return create_user(telegram_id, username, first_name), True
    return user, False


# ---------------------------------------------------------------------------
# Транзакции
# ---------------------------------------------------------------------------

def add_transaction(telegram_id: int, transaction: dict) -> None:
    """Сохраняет транзакцию в БД."""
    if "id" not in transaction:
        transaction = {**transaction, "id": str(uuid.uuid4())}

    row = {
        "id":          transaction["id"],
        "telegram_id": telegram_id,
        "type":        transaction.get("type", "expense"),
        "amount":      float(transaction["amount"]),
        "category":    transaction.get("category", "other"),
        "description": transaction.get("description", ""),
        "merchant":    transaction.get("merchant"),
        "source":      transaction.get("source", "text"),
        "created_at":  transaction.get("datetime", datetime.now().isoformat()),
    }
    try:
        _client().table("transactions").insert(row).execute()
    except Exception as e:
        logger.error(f"add_transaction({telegram_id}): {e}")


def get_transactions(telegram_id: int, since_days: int | None = None) -> list:
    """
    Возвращает транзакции пользователя, отсортированные от новых к старым.
    Если задан since_days — отдаёт только записи за последние N дней
    (по тарифным ограничениям истории).
    """
    try:
        from datetime import timedelta
        q = (
            _client()
            .table("transactions")
            .select("*")
            .eq("telegram_id", telegram_id)
            .order("created_at", desc=True)
        )
        if since_days is not None and since_days > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
            q = q.gte("created_at", cutoff)
        res = q.execute()
        # Нормализуем поле datetime для обратной совместимости с ботом
        txs = []
        for row in (res.data or []):
            txs.append(_row_to_tx(row))
        return txs
    except Exception as e:
        logger.error(f"get_transactions({telegram_id}): {e}")
        return []


def get_transaction(telegram_id: int, transaction_id: str) -> dict | None:
    """Возвращает одну транзакцию по ID."""
    try:
        res = (
            _client()
            .table("transactions")
            .select("*")
            .eq("id", transaction_id)
            .eq("telegram_id", telegram_id)
            .maybe_single()
            .execute()
        )
        return _row_to_tx(res.data) if res.data else None
    except Exception as e:
        logger.error(f"get_transaction({transaction_id}): {e}")
        return None


def update_transaction(telegram_id: int, transaction_id: str, updates: dict) -> dict | None:
    """Обновляет поля транзакции."""
    # Переименовываем datetime → created_at если передан
    db_updates = {}
    for k, v in updates.items():
        if k == "datetime":
            db_updates["created_at"] = v
        else:
            db_updates[k] = v

    try:
        res = (
            _client()
            .table("transactions")
            .update(db_updates)
            .eq("id", transaction_id)
            .eq("telegram_id", telegram_id)
            .execute()
        )
        return _row_to_tx(res.data[0]) if res.data else None
    except Exception as e:
        logger.error(f"update_transaction({transaction_id}): {e}")
        return None


def delete_transaction(telegram_id: int, transaction_id: str) -> bool:
    """Удаляет транзакцию. Возвращает True если запись была найдена."""
    try:
        res = (
            _client()
            .table("transactions")
            .delete()
            .eq("id", transaction_id)
            .eq("telegram_id", telegram_id)
            .execute()
        )
        return len(res.data or []) > 0
    except Exception as e:
        logger.error(f"delete_transaction({transaction_id}): {e}")
        return False


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _row_to_tx(row: dict) -> dict:
    """Приводит строку БД к формату транзакции, совместимому с кодом бота."""
    return {
        "id":          row["id"],
        "type":        row.get("type", "expense"),
        "amount":      float(row["amount"]),
        "category":    row.get("category", "other"),
        "description": row.get("description", ""),
        "merchant":    row.get("merchant"),
        "source":      row.get("source", "text"),
        # поле datetime — для обратной совместимости с хендлерами бота
        "datetime":    row.get("created_at", datetime.now().isoformat()),
    }


# ---------------------------------------------------------------------------
# Подписки и лимиты (миграция 002)
# ---------------------------------------------------------------------------

def _today_start_utc() -> str:
    """Начало текущих суток по UTC в ISO-формате."""
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def count_transactions_today(telegram_id: int, source: str | None = None) -> int:
    """Сколько транзакций у юзера за сегодня (UTC). Если задан source — фильтрует."""
    try:
        q = (
            _client()
            .table("transactions")
            .select("id", count="exact")
            .eq("telegram_id", telegram_id)
            .gte("created_at", _today_start_utc())
        )
        if source is not None:
            q = q.eq("source", source)
        res = q.execute()
        return res.count or 0
    except Exception as e:
        logger.error(f"count_transactions_today({telegram_id}, {source}): {e}")
        return 0


def count_transactions_today_in_sources(telegram_id: int, sources: list[str]) -> int:
    """Как count_transactions_today, но фильтрует по списку source'ов сразу.
    Нужно, чтобы лимит на «текстовые траты» одинаково учитывал и чат-бот
    (source='text'), и Mini App (source='miniapp') — иначе фронт обходит лимит."""
    if not sources:
        return 0
    try:
        res = (
            _client()
            .table("transactions")
            .select("id", count="exact")
            .eq("telegram_id", telegram_id)
            .gte("created_at", _today_start_utc())
            .in_("source", sources)
            .execute()
        )
        return res.count or 0
    except Exception as e:
        logger.error(f"count_transactions_today_in_sources({telegram_id}, {sources}): {e}")
        return 0


def count_events_today(telegram_id: int, event_type: str) -> int:
    """Сколько событий заданного типа у юзера за сегодня (UTC)."""
    try:
        res = (
            _client()
            .table("events")
            .select("id", count="exact")
            .eq("telegram_id", telegram_id)
            .eq("type", event_type)
            .gte("created_at", _today_start_utc())
            .execute()
        )
        return res.count or 0
    except Exception as e:
        logger.error(f"count_events_today({telegram_id}, {event_type}): {e}")
        return 0


def log_event(telegram_id: int, event_type: str, metadata: dict | None = None) -> None:
    """Запись события в таблицу events (для подсчёта лимитов и аналитики)."""
    try:
        _client().table("events").insert({
            "telegram_id": telegram_id,
            "type":        event_type,
            "metadata":    metadata or {},
        }).execute()
    except Exception as e:
        logger.warning(f"log_event({telegram_id}, {event_type}): {e}")


def has_event_ever(telegram_id: int, event_type: str) -> bool:
    """Был ли у юзера хоть один event указанного типа за всё время.
    Используется для one-shot подсказок («показать ровно один раз»)."""
    try:
        res = (
            _client().table("events").select("id")
            .eq("telegram_id", telegram_id)
            .eq("type", event_type)
            .limit(1).execute()
        )
        return bool(res.data)
    except Exception as e:
        logger.error(f"has_event_ever({telegram_id}, {event_type}): {e}")
        return False


def update_user_plan(
    telegram_id: int,
    plan: str,
    *,
    subscription_until: datetime | None = None,
    trial_until: datetime | None = None,
) -> None:
    """Обновляет план пользователя. None значения не трогаются."""
    patch: dict = {"plan": plan}
    if subscription_until is not None:
        patch["subscription_until"] = subscription_until.isoformat()
    if trial_until is not None:
        patch["trial_until"] = trial_until.isoformat()
    try:
        _client().table("users").update(patch).eq("telegram_id", telegram_id).execute()
    except Exception as e:
        logger.error(f"update_user_plan({telegram_id}, {plan}): {e}")


# Дефолтная регистрация юзера сейчас опирается на DEFAULT в схеме —
# plan='trial', trial_until=now()+7d. Если по какой-то причине эти поля
# не выставились (например, миграция ещё не применена), вернём sane defaults.
def ensure_trial_defaults(user: dict) -> dict:
    """Подстраховка: если в user нет колонок плана, добавляет дефолты в локальный dict."""
    from datetime import timedelta
    if not user.get("plan"):
        user["plan"] = "trial"
    if not user.get("trial_until"):
        user["trial_until"] = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    return user


def _month_start_utc() -> str:
    """Начало текущего календарного месяца по UTC в ISO."""
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def count_transactions_this_month(telegram_id: int, source: str | None = None) -> int:
    """Сколько транзакций у юзера с начала текущего календарного месяца (UTC)."""
    try:
        q = (
            _client()
            .table("transactions")
            .select("id", count="exact")
            .eq("telegram_id", telegram_id)
            .gte("created_at", _month_start_utc())
        )
        if source is not None:
            q = q.eq("source", source)
        res = q.execute()
        return res.count or 0
    except Exception as e:
        logger.error(f"count_transactions_this_month({telegram_id}, {source}): {e}")
        return 0


def count_transactions_this_month_in_sources(telegram_id: int, sources: list[str]) -> int:
    """Месячная версия count_transactions_today_in_sources."""
    if not sources:
        return 0
    try:
        res = (
            _client()
            .table("transactions")
            .select("id", count="exact")
            .eq("telegram_id", telegram_id)
            .gte("created_at", _month_start_utc())
            .in_("source", sources)
            .execute()
        )
        return res.count or 0
    except Exception as e:
        logger.error(f"count_transactions_this_month_in_sources({telegram_id}, {sources}): {e}")
        return 0


def count_events_this_month(telegram_id: int, event_type: str) -> int:
    """Сколько событий заданного типа у юзера с начала месяца (UTC)."""
    try:
        res = (
            _client()
            .table("events")
            .select("id", count="exact")
            .eq("telegram_id", telegram_id)
            .eq("type", event_type)
            .gte("created_at", _month_start_utc())
            .execute()
        )
        return res.count or 0
    except Exception as e:
        logger.error(f"count_events_this_month({telegram_id}, {event_type}): {e}")
        return 0


def activate_subscription(telegram_id: int, plan: str, days: int = 30) -> dict | None:
    """
    Активирует подписку: ставит plan, продлевает subscription_until на `days`
    от ТЕКУЩЕГО значения (если оно ещё в будущем) или от сейчас. Возвращает
    обновлённого пользователя.
    """
    from datetime import timedelta
    user = get_user(telegram_id) or {}
    now = datetime.now(timezone.utc)
    current_str = user.get("subscription_until")
    base = now
    if current_str:
        try:
            cur = datetime.fromisoformat(str(current_str).replace("Z", "+00:00"))
            if cur.tzinfo is None:
                cur = cur.replace(tzinfo=timezone.utc)
            if cur > now:
                base = cur
        except Exception:
            pass
    new_until = base + timedelta(days=days)
    patch = {"plan": plan, "subscription_until": new_until.isoformat()}
    try:
        res = _client().table("users").update(patch).eq("telegram_id", telegram_id).execute()
        log_event(telegram_id, "subscription_paid", {"plan": plan, "days": days, "until": new_until.isoformat()})
        return (res.data or [None])[0]
    except Exception as e:
        logger.error(f"activate_subscription({telegram_id}, {plan}): {e}")
        return None


def get_user_by_referral_code(code: str) -> dict | None:
    """Поиск пользователя по реферальному коду."""
    try:
        res = _client().table("users").select("*").eq("referral_code", code).maybe_single().execute()
        return res.data if res else None
    except Exception as e:
        logger.error(f"get_user_by_referral_code({code}): {e}")
        return None


def set_referred_by(telegram_id: int, referrer_id: int) -> None:
    """Записывает, кто пригласил юзера. Если уже записан — не трогает."""
    try:
        _client().table("users").update({"referred_by_user_id": referrer_id}) \
            .eq("telegram_id", telegram_id).is_("referred_by_user_id", "null").execute()
    except Exception as e:
        logger.error(f"set_referred_by({telegram_id}, {referrer_id}): {e}")


def extend_subscription_days(telegram_id: int, days: int, target_plan: str = "premium") -> dict | None:
    """
    Прибавляет подписке `days` дней (поверх существующей, если она в будущем).
    Если у юзера plan='trial' или 'free' — поднимает до `target_plan`.
    Если уже на премиум/pro — оставляет текущий plan, только продлевает.
    """
    from datetime import timedelta
    user = get_user(telegram_id) or {}
    now = datetime.now(timezone.utc)

    current_str = user.get("subscription_until")
    base = now
    if current_str:
        try:
            cur = datetime.fromisoformat(str(current_str).replace("Z", "+00:00"))
            if cur.tzinfo is None:
                cur = cur.replace(tzinfo=timezone.utc)
            if cur > now:
                base = cur
        except Exception:
            pass

    new_until = base + timedelta(days=days)
    current_plan = user.get("plan", "trial")
    plan = current_plan if current_plan in ("premium", "pro") else target_plan
    patch = {"plan": plan, "subscription_until": new_until.isoformat()}

    try:
        res = _client().table("users").update(patch).eq("telegram_id", telegram_id).execute()
        log_event(telegram_id, "subscription_extended", {"plan": plan, "days": days, "until": new_until.isoformat()})
        return (res.data or [None])[0]
    except Exception as e:
        logger.error(f"extend_subscription_days({telegram_id}, {days}): {e}")
        return None


def expire_trial(telegram_id: int) -> None:
    """Перевод юзера из trial в free."""
    try:
        _client().table("users").update({
            "plan": "free",
            "trial_expired_at": datetime.now(timezone.utc).isoformat(),
        }).eq("telegram_id", telegram_id).execute()
        log_event(telegram_id, "trial_expired", {})
    except Exception as e:
        logger.error(f"expire_trial({telegram_id}): {e}")


def mark_trial_warned(telegram_id: int) -> None:
    try:
        _client().table("users").update({
            "trial_warned_at": datetime.now(timezone.utc).isoformat(),
        }).eq("telegram_id", telegram_id).execute()
        log_event(telegram_id, "trial_warned", {})
    except Exception as e:
        logger.error(f"mark_trial_warned({telegram_id}): {e}")


def find_trials_about_to_expire(within_hours: int = 24) -> list[dict]:
    """Юзеры в триале, до конца < within_hours и ещё не уведомлённые."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    horizon = (now + timedelta(hours=within_hours)).isoformat()
    try:
        res = (
            _client().table("users").select("telegram_id,trial_until")
            .eq("plan", "trial")
            .lte("trial_until", horizon)
            .gte("trial_until", now.isoformat())
            .is_("trial_warned_at", "null")
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error(f"find_trials_about_to_expire: {e}")
        return []


def find_expired_trials() -> list[dict]:
    """Юзеры в триале, у которых trial_until уже прошёл."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        res = (
            _client().table("users").select("telegram_id,trial_until")
            .eq("plan", "trial")
            .lt("trial_until", now)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error(f"find_expired_trials: {e}")
        return []


def find_active_users(within_days: int = 14) -> list[dict]:
    """
    Возвращает юзеров, у которых была хотя бы одна транзакция за последние N дней.
    Используется для weekly summary и других массовых рассылок —
    мёртвых юзеров не трогаем.
    """
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=within_days)).isoformat()
    try:
        active = _client().table("transactions").select("telegram_id") \
            .gte("created_at", cutoff).execute().data or []
        active_ids = list({r["telegram_id"] for r in active})
        if not active_ids:
            return []
        res = _client().table("users").select("telegram_id,first_name,currency") \
            .in_("telegram_id", active_ids).execute()
        return res.data or []
    except Exception as e:
        logger.error(f"find_active_users: {e}")
        return []


def find_users_without_transactions_today() -> list[dict]:
    """
    Возвращает активных юзеров, которые сегодня (UTC) ещё не записали ни одной транзакции.
    «Активный» = есть хотя бы одна транзакция за последние 14 дней.
    """
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    cutoff_14d = (now - timedelta(days=14)).isoformat()
    try:
        # 1) Юзеры с активностью за 14 дней
        active = _client().table("transactions").select("telegram_id") \
            .gte("created_at", cutoff_14d).execute().data or []
        active_ids = list({r["telegram_id"] for r in active})
        if not active_ids:
            return []

        # 2) Кто из них уже записал что-то сегодня
        today_active = _client().table("transactions").select("telegram_id") \
            .gte("created_at", today_start).in_("telegram_id", active_ids).execute().data or []
        today_ids = {r["telegram_id"] for r in today_active}

        # 3) Возвращаем тех, кто активный, но сегодня ничего не записал
        to_remind = [tid for tid in active_ids if tid not in today_ids]
        if not to_remind:
            return []
        res = _client().table("users").select("telegram_id,first_name") \
            .in_("telegram_id", to_remind).execute()
        return res.data or []
    except Exception as e:
        logger.error(f"find_users_without_transactions_today: {e}")
        return []


# ---------------------------------------------------------------------------
# Кастомные категории
# ---------------------------------------------------------------------------

def get_custom_categories(telegram_id: int, type: str | None = None) -> list:
    """Возвращает кастомные категории пользователя."""
    try:
        q = _client().table("custom_categories").select("*").eq("telegram_id", telegram_id).order("created_at")
        if type in ("expense", "income"):
            q = q.eq("type", type)
        res = q.execute()
        return res.data or []
    except Exception as e:
        logger.error(f"get_custom_categories({telegram_id}): {e}")
        return []


def count_custom_categories(telegram_id: int) -> int:
    try:
        res = _client().table("custom_categories").select("id", count="exact").eq("telegram_id", telegram_id).execute()
        return res.count or 0
    except Exception as e:
        logger.error(f"count_custom_categories({telegram_id}): {e}")
        return 0


def add_custom_category(telegram_id: int, name: str, emoji: str, type_: str) -> dict | None:
    """Создаёт кастомную категорию. Возвращает созданную запись или None."""
    if type_ not in ("expense", "income"):
        return None
    try:
        res = _client().table("custom_categories").insert({
            "telegram_id": telegram_id,
            "name":        name.strip()[:50],
            "emoji":       (emoji or "📦").strip()[:8],
            "type":        type_,
        }).execute()
        return (res.data or [None])[0]
    except Exception as e:
        logger.error(f"add_custom_category({telegram_id}, {name}): {e}")
        return None


def delete_custom_category(telegram_id: int, cat_id: str) -> bool:
    try:
        res = _client().table("custom_categories").delete() \
            .eq("id", cat_id).eq("telegram_id", telegram_id).execute()
        return len(res.data or []) > 0
    except Exception as e:
        logger.error(f"delete_custom_category({cat_id}): {e}")
        return False


# ---------------------------------------------------------------------------
# Регулярные платежи
# ---------------------------------------------------------------------------

def get_recurring_payments(telegram_id: int, only_active: bool = True) -> list:
    try:
        q = _client().table("recurring_payments").select("*").eq("telegram_id", telegram_id).order("created_at")
        if only_active:
            q = q.eq("active", True)
        res = q.execute()
        return res.data or []
    except Exception as e:
        logger.error(f"get_recurring_payments({telegram_id}): {e}")
        return []


def count_recurring_payments(telegram_id: int) -> int:
    try:
        res = _client().table("recurring_payments").select("id", count="exact") \
            .eq("telegram_id", telegram_id).eq("active", True).execute()
        return res.count or 0
    except Exception as e:
        logger.error(f"count_recurring_payments({telegram_id}): {e}")
        return 0


def add_recurring_payment(telegram_id: int, *, type_: str, amount: float, category: str,
                          description: str, period_days: int, first_run_at: datetime) -> dict | None:
    if type_ not in ("expense", "income"):
        return None
    try:
        res = _client().table("recurring_payments").insert({
            "telegram_id": telegram_id,
            "type":        type_,
            "amount":      float(amount),
            "category":    category,
            "description": description[:200],
            "period_days": int(period_days),
            "next_run_at": first_run_at.isoformat(),
            "active":      True,
        }).execute()
        return (res.data or [None])[0]
    except Exception as e:
        logger.error(f"add_recurring_payment({telegram_id}): {e}")
        return None


def delete_recurring_payment(telegram_id: int, rp_id: str) -> bool:
    try:
        res = _client().table("recurring_payments").delete() \
            .eq("id", rp_id).eq("telegram_id", telegram_id).execute()
        return len(res.data or []) > 0
    except Exception as e:
        logger.error(f"delete_recurring_payment({rp_id}): {e}")
        return False


def find_due_recurring_payments() -> list:
    """Все активные регулярные платежи, у которых next_run_at <= сейчас."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        res = _client().table("recurring_payments").select("*") \
            .eq("active", True).lte("next_run_at", now).execute()
        return res.data or []
    except Exception as e:
        logger.error(f"find_due_recurring_payments: {e}")
        return []


def reschedule_recurring_payment(rp_id: str, next_run_at: datetime) -> None:
    try:
        _client().table("recurring_payments").update({
            "next_run_at": next_run_at.isoformat(),
            "last_run_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", rp_id).execute()
    except Exception as e:
        logger.error(f"reschedule_recurring_payment({rp_id}): {e}")


# ---------------------------------------------------------------------------
# Бан-список
# ---------------------------------------------------------------------------

def is_banned(telegram_id: int) -> bool:
    try:
        res = _client().table("banned_users").select("telegram_id") \
            .eq("telegram_id", telegram_id).limit(1).execute()
        return bool(res.data)
    except Exception as e:
        logger.error(f"is_banned({telegram_id}): {e}")
        return False


def ban_user(telegram_id: int, reason: str = "", banned_by: int | None = None) -> bool:
    try:
        _client().table("banned_users").upsert({
            "telegram_id": telegram_id,
            "reason": reason[:200],
            "banned_by": banned_by,
        }).execute()
        return True
    except Exception as e:
        logger.error(f"ban_user({telegram_id}): {e}")
        return False


def unban_user(telegram_id: int) -> bool:
    try:
        res = _client().table("banned_users").delete().eq("telegram_id", telegram_id).execute()
        return len(res.data or []) > 0
    except Exception as e:
        logger.error(f"unban_user({telegram_id}): {e}")
        return False


def find_users_with_many_limit_hits(within_hours: int = 1, threshold: int = 5) -> list[dict]:
    """Возвращает [(telegram_id, count), ...] кого надо алертить — много limit_hit за окно."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=within_hours)).isoformat()
    try:
        res = _client().table("events").select("telegram_id") \
            .eq("type", "limit_hit").gte("created_at", cutoff).execute()
        from collections import Counter
        c = Counter(r["telegram_id"] for r in (res.data or []))
        return [{"telegram_id": uid, "count": n} for uid, n in c.items() if n >= threshold]
    except Exception as e:
        logger.error(f"find_users_with_many_limit_hits: {e}")
        return []


# ---------------------------------------------------------------------------
# Аналитика для админ-команды
# ---------------------------------------------------------------------------

def admin_stats() -> dict:
    """Сводка для админа: юзеры, транзакции, активность."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()
    try:
        users_all   = _client().table("users").select("plan").execute().data or []
        plans_cnt   = {}
        for u in users_all:
            plans_cnt[u["plan"]] = plans_cnt.get(u["plan"], 0) + 1
        users_week  = _client().table("users").select("telegram_id", count="exact") \
            .gte("created_at", week_ago).execute().count or 0

        tx_total = _client().table("transactions").select("id", count="exact").execute().count or 0
        tx_today = _client().table("transactions").select("id", count="exact") \
            .gte("created_at", today).execute().count or 0
        tx_week  = _client().table("transactions").select("id", count="exact") \
            .gte("created_at", week_ago).execute().count or 0

        limit_today = _client().table("events").select("id", count="exact") \
            .eq("type", "limit_hit").gte("created_at", today).execute().count or 0
        ai_today = _client().table("events").select("id", count="exact") \
            .eq("type", "ai_question").gte("created_at", today).execute().count or 0
        paid_total = _client().table("events").select("id", count="exact") \
            .eq("type", "subscription_paid").execute().count or 0

        return {
            "users_total":   len(users_all),
            "users_by_plan": plans_cnt,
            "users_week":    users_week,
            "tx_total":      tx_total,
            "tx_today":      tx_today,
            "tx_week":       tx_week,
            "limit_today":   limit_today,
            "ai_today":      ai_today,
            "paid_total":    paid_total,
        }
    except Exception as e:
        logger.error(f"admin_stats: {e}")
        return {}
