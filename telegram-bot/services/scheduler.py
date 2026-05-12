"""Фоновые задачи: завершение триала, уведомления, ежедневные напоминания."""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from aiogram import Bot

from services import storage

logger = logging.getLogger(__name__)

# Asia/Bishkek = UTC+6. Ежедневное напоминание в 21:00 Bishkek = 15:00 UTC.
DAILY_REMINDER_UTC_HOUR = 15


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

    while True:
        try:
            await trial_sweep(bot)
            await process_recurring_payments(bot)

            now_utc = datetime.now(timezone.utc)
            today_utc = now_utc.date()
            if now_utc.hour == DAILY_REMINDER_UTC_HOUR and last_reminder_date != today_utc:
                await daily_reminders(bot)
                last_reminder_date = today_utc
        except Exception as e:
            logger.error(f"scheduler_loop tick failed: {e}")

        await asyncio.sleep(60)
