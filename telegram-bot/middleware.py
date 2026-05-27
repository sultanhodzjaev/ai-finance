"""Aiogram middleware: бан-чек + anti-flood."""
import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from services import storage

logger = logging.getLogger(__name__)

# Минимальный gap между сообщениями одного юзера. Раньше 2.0 — это блокировало
# нормальное поведение «записываю несколько трат подряд». Снижено до 0.4с —
# хватает чтобы отбить скриптовый flood, не мешая живому юзеру.
FLOOD_RATE_SEC = 0.4
# Если юзер регулярно пишет в пределах окна — после N сообщений предупреждаем.
FLOOD_WARN_BURST = 5
FLOOD_WARN_COOLDOWN_SEC = 30
# Сколько секунд кешируем ban-статус, чтобы не дёргать БД каждое сообщение
BAN_CACHE_TTL_SEC = 60


class BanAndFloodMiddleware(BaseMiddleware):
    """
    1. Если юзер в banned_users — silent ignore.
    2. Anti-flood с мягким поведением: при попадании в окно даём sleep,
       чтобы сообщение всё-таки обработалось, а не «потерялось» молча.
       Если юзер реально долбит >FLOOD_WARN_BURST за окно — отвечаем
       короткой подсказкой и пропускаем апдейт.
    """

    def __init__(self) -> None:
        self._last_msg_ts: dict[int, float] = {}
        self._burst_count: dict[int, int] = {}
        self._last_warn_ts: dict[int, float] = {}
        self._ban_cache: dict[int, tuple[float, bool]] = {}

    def _cached_ban(self, uid: int) -> bool:
        now = time.monotonic()
        cached = self._ban_cache.get(uid)
        if cached and now - cached[0] < BAN_CACHE_TTL_SEC:
            return cached[1]
        banned = storage.is_banned(uid)
        self._ban_cache[uid] = (now, banned)
        return banned

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.from_user:
            return await handler(event, data)

        uid = event.from_user.id

        # 1. Бан
        if self._cached_ban(uid):
            logger.info(f"ban middleware: dropped message from banned uid={uid}")
            return

        # 2. Anti-flood
        now = time.monotonic()
        last = self._last_msg_ts.get(uid, 0.0)
        gap = now - last

        if gap < FLOOD_RATE_SEC:
            burst = self._burst_count.get(uid, 0) + 1
            self._burst_count[uid] = burst

            if burst > FLOOD_WARN_BURST:
                # Реальный долбёж. Один раз в FLOOD_WARN_COOLDOWN_SEC шлём warn
                # и пропускаем апдейт.
                last_warn = self._last_warn_ts.get(uid, 0.0)
                if now - last_warn > FLOOD_WARN_COOLDOWN_SEC:
                    self._last_warn_ts[uid] = now
                    try:
                        await event.answer("⏳ Не так быстро — пара секунд на обработку.")
                    except Exception:
                        pass
                logger.info(f"flood: burst-throttled uid={uid} burst={burst}")
                return

            # Мягкая пауза: добиваем gap до FLOOD_RATE_SEC и обрабатываем дальше.
            await asyncio.sleep(FLOOD_RATE_SEC - gap)
            self._last_msg_ts[uid] = time.monotonic()
            return await handler(event, data)

        # gap >= FLOOD_RATE_SEC — обычный путь, сбрасываем burst.
        self._burst_count[uid] = 0
        self._last_msg_ts[uid] = now
        return await handler(event, data)
