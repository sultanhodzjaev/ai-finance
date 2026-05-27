"""Фоновые задачи: завершение триала, уведомления, ежедневные напоминания."""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from aiogram import Bot

from services import gemini, storage

logger = logging.getLogger(__name__)

# Asia/Bishkek = UTC+6. Ежедневное напоминание в 21:00 Bishkek = 15:00 UTC.
DAILY_REMINDER_UTC_HOUR = 15
# Weekly summary — воскресенье 20:00 Bishkek = воскресенье 14:00 UTC.
# weekday(): Mon=0 … Sun=6.
WEEKLY_SUMMARY_UTC_HOUR = 14
WEEKLY_SUMMARY_WEEKDAY = 6


async def _send_safe(bot: Bot, chat_id: int, text: str) -> bool:
    try:
        await bot.send_message(chat_id, text, parse_mode="HTML", disable_notification=False)
        return True
    except Exception as e:
        logger.warning(f"send to {chat_id} failed: {e}")
        return False


async def trial_sweep(bot: Bot) -> None:
    """
    1. Предупреждаем юзеров за 24 часа до конца триала (один раз).
    2. Тех, у кого триал уже истёк — переводим в free и шлём уведомление.
    """
    # 1. Предупреждения
    warned = 0
    for u in storage.find_trials_about_to_expire(within_hours=24):
        uid = u.get("telegram_id")
        if not uid:
            continue
        ok = await _send_safe(
            bot, uid,
            "⏳ <b>До конца триала меньше 24 часов</b>\n\n"
            "Скоро лимиты упадут до Free (2 траты/день, без AI и фото).\n"
            "Чтобы оставить полный доступ — /upgrade.\n"
            "Можно также пригласить друга и получить +14 дней — /invite."
        )
        if ok:
            storage.mark_trial_warned(uid)
            warned += 1

    # 2. Истёкшие
    expired = 0
    for u in storage.find_expired_trials():
        uid = u.get("telegram_id")
        if not uid:
            continue
        storage.expire_trial(uid)
        await _send_safe(
            bot, uid,
            "📭 <b>Триал закончился</b>\n\n"
            "Ты теперь на Free: 2 траты в день, история 30 дней.\n"
            "Чтобы вернуть полный доступ — /upgrade.\n"
            "Или пригласи друга и получи +14 дней — /invite."
        )
        expired += 1

    if warned or expired:
        logger.info(f"trial_sweep: warned={warned}, expired={expired}")


async def weekly_summary(bot: Bot) -> None:
    """
    Раз в неделю шлёт активным юзерам итоги последних 7 дней —
    топ-категории, дельта к прошлой неделе, аномалии, одно действие.
    Текст готовит gemini.generate_weekly_summary.
    """
    sent = 0
    skipped = 0
    for u in storage.find_active_users(within_days=14):
        uid = u.get("telegram_id")
        if not uid:
            continue
        if storage.is_banned(uid):
            continue
        currency = u.get("currency") or "KGS"
        first_name = u.get("first_name") or ""
        try:
            txs = storage.get_transactions(uid, since_days=14)
            html = await gemini.generate_weekly_summary(currency, txs, first_name=first_name)
        except Exception as e:
            logger.warning(f"weekly_summary build for {uid} failed: {e}")
            continue
        if not html:
            skipped += 1
            continue

        cleaned = html.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0].rstrip()

        try:
            await bot.send_message(uid, cleaned, parse_mode="HTML", disable_web_page_preview=True)
            sent += 1
            storage.log_event(uid, "weekly_summary_sent", {})
        except Exception as e:
            logger.warning(f"weekly_summary send to {uid} failed: {e}")
        # Bot API лимит ~30 msg/sec — закладываем запас.
        await asyncio.sleep(0.05)

    logger.info(f"weekly_summary: sent={sent}, skipped_no_data={skipped}")


async def daily_reminders(bot: Bot) -> None:
    """Ежедневное напоминание тем, кто сегодня не записал ни одной траты."""
    sent = 0
    for u in storage.find_users_without_transactions_today():
        uid = u.get("telegram_id")
        if not uid:
            continue
        name = u.get("first_name") or "Друг"
        ok = await _send_safe(
            bot, uid,
            f"👋 {name}, сегодня ещё не было ни одной записи.\n"
            "Чтобы статистика была честной — лучше внести траты, пока помнишь. "
            "Просто напиши мне «250 на обед» — я сам разберусь."
        )
        if ok:
            storage.log_event(uid, "reminder_sent", {})
            sent += 1
    if sent:
        logger.info(f"daily_reminders: sent={sent}")


def _admin_id() -> int | None:
    import os
    raw = os.getenv("ADMIN_ID") or os.getenv("OWNER_ID")
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


# Чтобы не спамить админа одинаковыми алертами — запоминаем uid+час
_abuse_alerted: set[str] = set()


async def detect_abuse(bot: Bot) -> None:
    """Если у юзера >5 limit_hit за последний час — уведомляем админа."""
    admin = _admin_id()
    if not admin:
        return
    suspicious = storage.find_users_with_many_limit_hits(within_hours=1, threshold=5)
    hour_tag = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    for s in suspicious:
        uid = s["telegram_id"]
        key = f"{uid}:{hour_tag}"
        if key in _abuse_alerted:
            continue
        _abuse_alerted.add(key)
        try:
            await bot.send_message(
                admin,
                f"⚠️ <b>Подозрительная активность</b>\n\n"
                f"Юзер <code>{uid}</code> упёрся в лимиты <b>{s['count']}</b> раз за последний час.\n"
                f"Команды: <code>/ban {uid}</code> | <code>/unban {uid}</code>",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"abuse alert to admin failed: {e}")


async def process_recurring_payments(bot: Bot) -> None:
    """Создаёт транзакции по всем due-регулярным платежам и переносит next_run_at."""
    created = 0
    for rp in storage.find_due_recurring_payments():
        try:
            storage.add_transaction(rp["telegram_id"], {
                "type":        rp["type"],
                "amount":      float(rp["amount"]),
                "category":    rp["category"],
                "description": rp["description"] or "Регулярный платёж",
                "merchant":    None,
                "source":      "recurring",
                "datetime":    datetime.now(timezone.utc).isoformat(),
            })
            next_at = datetime.now(timezone.utc) + timedelta(days=int(rp["period_days"]))
            storage.reschedule_recurring_payment(rp["id"], next_at)
            await _send_safe(
                bot, rp["telegram_id"],
                f"🔁 Регулярный {'доход' if rp['type'] == 'income' else 'расход'}: "
                f"<b>{rp['amount']}</b> «{rp['description'] or rp['category']}». "
                f"Следующий: {next_at.strftime('%Y-%m-%d')}."
            )
            created += 1
        except Exception as e:
            logger.error(f"recurring process {rp.get('id')}: {e}")
    if created:
        logger.info(f"process_recurring_payments: created={created}")


async def scheduler_loop(bot: Bot) -> None:
    """
    Главный цикл планировщика. Тикает раз в минуту.
    - trial_sweep — каждый тик
    - process_recurring_payments — каждый тик
    - daily_reminders — один раз в день в 21:00 Asia/Bishkek (15:00 UTC)
    """
    logger.info("scheduler_loop: started")
    last_reminder_date = None
    last_weekly_date = None

    while True:
        try:
            await trial_sweep(bot)
            await process_recurring_payments(bot)
            await detect_abuse(bot)

            now_utc = datetime.now(timezone.utc)
            today_utc = now_utc.date()
            if now_utc.hour == DAILY_REMINDER_UTC_HOUR and last_reminder_date != today_utc:
                await daily_reminders(bot)
                last_reminder_date = today_utc
            if (
                now_utc.weekday() == WEEKLY_SUMMARY_WEEKDAY
                and now_utc.hour == WEEKLY_SUMMARY_UTC_HOUR
                and last_weekly_date != today_utc
            ):
                await weekly_summary(bot)
                last_weekly_date = today_utc
        except Exception as e:
            logger.error(f"scheduler_loop tick failed: {e}")

        await asyncio.sleep(60)
