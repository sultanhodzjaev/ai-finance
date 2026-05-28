import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Query

from api.auth import get_telegram_id, validate_init_data, parse_init_data_user
from services.storage import (
    get_user, get_or_create_user, get_transactions, get_transaction,
    update_transaction, delete_transaction, add_transaction,
)
from utils.categories import CATEGORIES, INCOME_CATEGORIES

router = APIRouter(prefix="/miniapp/api")


def require_auth(init_data: str) -> int:
    telegram_id = get_telegram_id(init_data)
    if not telegram_id:
        raise HTTPException(status_code=401, detail="Invalid initData")
    return telegram_id


def ensure_user(init_data: str, telegram_id: int) -> dict:
    """
    Возвращает пользователя, авто-создавая его если он открыл Mini App
    до команды /start в боте.
    """
    user = get_user(telegram_id)
    if not user:
        # Берём имя из initData без проверки хэша (только для регистрации)
        tg_user = parse_init_data_user(init_data) or {}
        user = get_or_create_user(
            telegram_id=telegram_id,
            username=tg_user.get("username", ""),
            first_name=tg_user.get("first_name", "Друг"),
        )
    return user


@router.get("/me")
async def get_me(x_init_data: str = Header(...)):
    """Данные текущего пользователя. Авто-создаёт пользователя если нужно."""
    telegram_id = require_auth(x_init_data)
    user = ensure_user(x_init_data, telegram_id)
    return {
        "telegram_id": user["telegram_id"],
        "first_name":  user["first_name"],
        "currency":    user["currency"],
    }


# Список валют дублирует handlers.onboarding.CURRENCIES — единый источник правды
# был бы лучше, но для пяти строк это overkill.
CURRENCY_LABELS = {
    "KGS": "🇰🇬 Сом (KGS)",
    "KZT": "🇰🇿 Тенге (KZT)",
    "RUB": "🇷🇺 Рубль (RUB)",
    "UZS": "🇺🇿 Сум (UZS)",
    "USD": "💵 Доллар (USD)",
}


@router.get("/currencies")
async def list_currencies():
    """Список доступных валют для picker'а в Mini App."""
    return {"currencies": [{"code": c, "label": l} for c, l in CURRENCY_LABELS.items()]}


@router.patch("/me/currency")
async def update_currency(payload: dict, x_init_data: str = Header(...)):
    """Смена валюты юзера прямо из Mini App. Старые транзакции не пересчитываются."""
    from services.storage import update_user_currency, log_event
    telegram_id = require_auth(x_init_data)
    ensure_user(x_init_data, telegram_id)
    code = (payload.get("currency") or "").upper()
    if code not in CURRENCY_LABELS:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="unknown currency")
    update_user_currency(telegram_id, code)
    log_event(telegram_id, "currency_set", {"currency": code, "source": "miniapp"})
    return {"ok": True, "currency": code}


@router.get("/me/invite")
async def get_invite(x_init_data: str = Header(...)):
    """Реферальная ссылка юзера + счётчик приглашённых."""
    import os
    from services.storage import _client
    telegram_id = require_auth(x_init_data)
    user = ensure_user(x_init_data, telegram_id)
    code = user.get("referral_code")
    if not code:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="referral code not assigned yet")

    bot_username = os.getenv("BOT_USERNAME", "smartcash_ai_bot")
    link = f"https://t.me/{bot_username}?start=ref_{code}"
    try:
        res = _client().table("events").select("id", count="exact") \
            .eq("telegram_id", telegram_id) \
            .eq("type", "referral_invited") \
            .execute()
        invited = res.count or 0
    except Exception:
        invited = 0

    return {
        "link":          link,
        "code":          code,
        "invited_count": invited,
        "bonus_days":    14,
    }


@router.get("/transactions")
async def list_transactions(
    x_init_data: str = Header(...),
    type: Optional[str] = Query(None, description="Фильтр: income, expense или не указан"),
):
    """Все транзакции пользователя в пределах истории, разрешённой его тарифом."""
    from services import plans
    telegram_id = require_auth(x_init_data)
    user = ensure_user(x_init_data, telegram_id)
    plan = plans.effective_plan(user)
    history_days = plans.LIMITS.get(plan, {}).get("history_days")  # None = безлимит
    txs = get_transactions(telegram_id, since_days=history_days)

    if type in ("income", "expense"):
        txs = [tx for tx in txs if tx.get("type", "expense") == type]

    return {"transactions": sorted(txs, key=lambda t: t["datetime"], reverse=True)}


@router.post("/transactions")
async def create_transaction(payload: dict, x_init_data: str = Header(...)):
    """Создать транзакцию из Mini App (без AI)."""
    telegram_id = require_auth(x_init_data)
    ensure_user(x_init_data, telegram_id)
    tx = {
        "id":          str(uuid.uuid4()),
        "type":        payload.get("type", "expense"),
        "amount":      float(payload["amount"]),
        "category":    payload.get("category", "other"),
        "description": payload.get("description", ""),
        "merchant":    None,
        "datetime":    datetime.now().isoformat(),
        "source":      "miniapp",
    }
    add_transaction(telegram_id, tx)
    return tx


@router.patch("/transactions/{tx_id}")
async def edit_transaction(tx_id: str, payload: dict, x_init_data: str = Header(...)):
    """Обновить сумму, категорию или описание транзакции."""
    telegram_id = require_auth(x_init_data)
    allowed = {"amount", "category", "description", "type"}
    updates = {k: v for k, v in payload.items() if k in allowed}
    if "amount" in updates:
        updates["amount"] = float(updates["amount"])
    tx = update_transaction(telegram_id, tx_id, updates)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return tx


@router.delete("/transactions/{tx_id}")
async def remove_transaction(tx_id: str, x_init_data: str = Header(...)):
    """Удалить транзакцию."""
    telegram_id = require_auth(x_init_data)
    ok = delete_transaction(telegram_id, tx_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {"success": True}


@router.get("/stats")
async def get_stats(x_init_data: str = Header(...)):
    """Статистика доходов и расходов за текущий месяц (в пределах разрешённой истории)."""
    from services import plans
    telegram_id = require_auth(x_init_data)
    user = ensure_user(x_init_data, telegram_id)
    history_days = plans.LIMITS.get(plans.effective_plan(user), {}).get("history_days")
    txs = get_transactions(telegram_id, since_days=history_days)
    now = datetime.now()

    month_txs = [
        t for t in txs
        if datetime.fromisoformat(t["datetime"]).month == now.month
        and datetime.fromisoformat(t["datetime"]).year  == now.year
    ]

    expenses = [t for t in month_txs if t.get("type", "expense") == "expense"]
    incomes  = [t for t in month_txs if t.get("type") == "income"]

    expense_by_category: dict[str, float] = {}
    income_by_category:  dict[str, float] = {}
    expense_by_day:      dict[str, float] = {}
    income_by_day:       dict[str, float] = {}

    for t in expenses:
        expense_by_category[t["category"]] = expense_by_category.get(t["category"], 0) + t["amount"]
        day = datetime.fromisoformat(t["datetime"]).strftime("%Y-%m-%d")
        expense_by_day[day] = expense_by_day.get(day, 0) + t["amount"]

    for t in incomes:
        income_by_category[t["category"]] = income_by_category.get(t["category"], 0) + t["amount"]
        day = datetime.fromisoformat(t["datetime"]).strftime("%Y-%m-%d")
        income_by_day[day] = income_by_day.get(day, 0) + t["amount"]

    total_expense = sum(expense_by_category.values())
    total_income  = sum(income_by_category.values())

    from utils.streak import compute_streak_days
    streak = compute_streak_days(txs)

    return {
        "total_income":        total_income,
        "total_expense":       total_expense,
        "balance":             total_income - total_expense,
        "transaction_count":   len(month_txs),
        "expense_by_category": expense_by_category,
        "income_by_category":  income_by_category,
        "expense_by_day":      expense_by_day,
        "income_by_day":       income_by_day,
        "streak_days":         streak,
    }


@router.get("/categories")
async def list_categories(x_init_data: str = Header(...)):
    """Списки категорий расходов и доходов: встроенные + кастомные пользователя."""
    from services import storage
    telegram_id = require_auth(x_init_data)
    ensure_user(x_init_data, telegram_id)
    customs = storage.get_custom_categories(telegram_id)
    custom_expense = [
        {"id": c["id"], "name": c["name"], "emoji": c["emoji"], "custom": True}
        for c in customs if c["type"] == "expense"
    ]
    custom_income = [
        {"id": c["id"], "name": c["name"], "emoji": c["emoji"], "custom": True}
        for c in customs if c["type"] == "income"
    ]
    return {
        "expense_categories": CATEGORIES + custom_expense,
        "income_categories":  INCOME_CATEGORIES + custom_income,
    }


@router.get("/plan")
async def get_plan(x_init_data: str = Header(...)):
    """Возвращает текущий план юзера, лимиты и использование за период."""
    from services import plans, storage
    telegram_id = require_auth(x_init_data)
    user = ensure_user(x_init_data, telegram_id)

    plan = plans.effective_plan(user)
    plan_limits = plans.LIMITS.get(plan, {})

    def _used(action: str) -> int:
        period = plans.period_for(action)
        if action == "transaction":
            return (storage.count_transactions_today(telegram_id, source="text")
                    if period == "day"
                    else storage.count_transactions_this_month(telegram_id, source="text"))
        if action == "photo":
            return (storage.count_transactions_today(telegram_id, source="photo")
                    if period == "day"
                    else storage.count_transactions_this_month(telegram_id, source="photo"))
        if action == "ai_question":
            return (storage.count_events_today(telegram_id, "ai_question")
                    if period == "day"
                    else storage.count_events_this_month(telegram_id, "ai_question"))
        if action == "voice":
            return (storage.count_transactions_today(telegram_id, source="voice")
                    if period == "day"
                    else storage.count_transactions_this_month(telegram_id, source="voice"))
        return 0

    runtime_actions = ["transaction", "photo", "ai_question", "voice"]
    usage = {}
    for a in runtime_actions:
        usage[a] = {
            "used":   _used(a),
            "limit":  plans.limit_for(plan, a),
            "period": plans.period_for(a),
        }

    import os
    bot_username = os.environ.get("BOT_USERNAME", "smartcash_ai_bot")
    referral_code = user.get("referral_code") or ""
    invite_link = f"https://t.me/{bot_username}?start=ref_{referral_code}" if referral_code else ""

    return {
        "plan":               plan,
        "plan_title":         plans.PLAN_TITLE.get(plan, plan),
        "trial_until":        user.get("trial_until"),
        "subscription_until": user.get("subscription_until"),
        "limits":             plan_limits,
        "usage":              usage,
        "pricing": {
            plans.PLAN_PREMIUM: {"usd": plans.PRICE_USD[plans.PLAN_PREMIUM]},
            plans.PLAN_PRO:     {"usd": plans.PRICE_USD[plans.PLAN_PRO]},
        },
        "referral": {
            "code":         referral_code,
            "invite_link":  invite_link,
            "bonus_days":   14,
        },
    }


@router.post("/upgrade/invoice")
async def create_upgrade_invoice(
    body: dict,
    x_init_data: str = Header(...),
):
    """
    Создаёт инвойс на подписку через Lava.top.
    Body: { "tier": "premium" | "pro" }
    Возвращает: { "payment_url": "https://...", "contract_id": "<uuid>" }
    """
    from services import plans, storage, lava

    telegram_id = require_auth(x_init_data)
    ensure_user(x_init_data, telegram_id)

    tier = (body or {}).get("tier")
    if tier not in (plans.PLAN_PREMIUM, plans.PLAN_PRO):
        raise HTTPException(status_code=400, detail="Invalid tier")

    offer_id = plans.LAVA_OFFER_IDS.get(tier)
    if not offer_id:
        raise HTTPException(status_code=400, detail="No offer for tier")

    storage.log_event(telegram_id, "upgrade_clicked", {"tier": tier, "source": "miniapp", "provider": "lava"})

    invoice = await lava.create_subscription(telegram_id=telegram_id, offer_id=offer_id)
    if not invoice or not invoice.get("paymentUrl"):
        raise HTTPException(status_code=502, detail="Lava invoice creation failed")

    storage.log_event(telegram_id, "lava_invoice_created", {
        "tier": tier, "contract_id": invoice.get("id", ""), "source": "miniapp",
    })

    return {"payment_url": invoice["paymentUrl"], "contract_id": invoice.get("id", "")}


@router.post("/export.csv")
async def export_csv(x_init_data: str = Header(...)):
    """
    Готовит CSV всех доступных транзакций пользователя и отправляет файлом
    в чат с ботом через sendDocument. Возвращает {sent: true}.
    Учитывает лимиты тарифа: history_days, exports_per_month / exports_total.
    """
    from datetime import datetime, timezone
    from io import StringIO
    import csv as csvmod
    import httpx
    import os

    from services import plans, storage
    telegram_id = require_auth(x_init_data)
    user = ensure_user(x_init_data, telegram_id)
    plan = plans.effective_plan(user)
    limits = plans.LIMITS.get(plan, {})

    # Проверяем лимит на количество экспортов
    if plan == plans.PLAN_TRIAL:
        cap = limits.get("exports_total")
    else:
        cap = limits.get("exports_per_month")
    used = storage.count_events_this_month(telegram_id, "export_csv")
    if cap is None or cap == 0:
        raise HTTPException(status_code=403, detail="Экспорт недоступен на твоём плане. Купи Premium — /upgrade")
    if used >= cap:
        raise HTTPException(status_code=429, detail=f"Лимит экспортов исчерпан ({used}/{cap}). Обновится в следующем периоде.")

    history_days = limits.get("history_days")
    txs = storage.get_transactions(telegram_id, since_days=history_days)

    from utils.categories import get_category_by_id
    TYPE_RU = {"income": "Доход", "expense": "Расход"}
    SOURCE_RU = {"text": "Текст", "photo": "Фото", "voice": "Голос", "miniapp": "Mini App"}

    buf = StringIO()
    # delimiter=';' — Excel в ru-локали по умолчанию ожидает ; (иначе строка попадёт в одну ячейку)
    w = csvmod.writer(buf, delimiter=';')
    w.writerow(["Дата", "Тип", "Сумма", "Валюта", "Категория", "Описание", "Где", "Источник"])
    currency = user.get("currency", "KGS")
    for t in txs:
        cat = get_category_by_id(t.get("category", "")) or {}
        cat_name = cat.get("name") or t.get("category", "")
        w.writerow([
            t.get("datetime", "")[:19].replace("T", " "),
            TYPE_RU.get(t.get("type", "expense"), t.get("type", "")),
            t.get("amount", 0),
            currency,
            cat_name,
            t.get("description", ""),
            t.get("merchant") or "",
            SOURCE_RU.get(t.get("source", "text"), t.get("source", "")),
        ])
    csv_bytes = buf.getvalue().encode("utf-8-sig")  # BOM, чтобы Excel ел кириллицу

    bot_token = os.environ.get("BOT_TOKEN")
    if not bot_token:
        raise HTTPException(status_code=500, detail="Bot misconfigured")

    fname = f"ai-finansist-{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendDocument",
                data={
                    "chat_id": telegram_id,
                    "caption": f"📥 Твой экспорт: {len(txs)} транзакций. Сохрани файл локально.",
                },
                files={"document": (fname, csv_bytes, "text/csv")},
            )
        data = resp.json()
        if not data.get("ok"):
            raise HTTPException(status_code=502, detail=f"sendDocument: {data.get('description', 'unknown')}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"sendDocument error: {e}")

    storage.log_event(telegram_id, "export_csv", {"plan": plan, "rows": len(txs)})
    return {"sent": True, "rows": len(txs), "filename": fname}
