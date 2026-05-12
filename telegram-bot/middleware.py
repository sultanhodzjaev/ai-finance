"""Aiogram middleware: бан-чек + anti-flood."""
import logging
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from services import storage

logger = logging.getLogger(__name__)

# Скрипт-юзер не сможет постить чаще чем 1 сообщение в FLOOD_RATE_SEC секунд
FLOOD_RATE_SEC = 2.0
# Сколько секунд кешируем ban-статус, чтобы не дёргать БД каждое сообщение
BAN_CACHE_TTL_SEC = 60


class BanAndFloodMiddleware(BaseMiddleware):
    """
    1. Если юзер в banned_users — silent ignore.
    2. Если шлёт быстрее FLOOD_RATE_SEC — silent ignore.
    Применяется к Message, остальные апдейты пропускаются как есть.
    """

    def __init__(self) -> None:
        self._last_msg_ts: dict[int, float] = {}
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
        if now - last < FLOOD_RATE_SEC:
            logger.info(f"flood middleware: throttled uid={uid} (gap={now-last:.2f}s)")
            return
        self._last_msg_ts[uid] = now

        return await handler(event, data)
