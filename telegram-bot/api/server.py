import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from api.routes import router

app = FastAPI(title="AI-финансист Mini App")


class IPRateLimitMiddleware(BaseHTTPMiddleware):
    """Простой rate-limit на API: max RATE запросов в PERIOD секунд на IP."""
    RATE = 60        # запросов
    PERIOD = 60.0    # секунд (1 минута)

    def __init__(self, app):
        super().__init__(app)
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        # Применяем только к /miniapp/api/*, статику не считаем
        if not request.url.path.startswith("/miniapp/api"):
            return await call_next(request)

        # Берём IP клиента (учитываем X-Forwarded-For от Caddy)
        ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() \
            or (request.client.host if request.client else "unknown")

        now = time.monotonic()
        bucket = self._hits[ip]
        # выкидываем устаревшие
        while bucket and now - bucket[0] > self.PERIOD:
            bucket.popleft()
        if len(bucket) >= self.RATE:
            return JSONResponse({"detail": "Too many requests"}, status_code=429)
        bucket.append(now)
        return await call_next(request)


# Rate-limit раньше CORS, чтобы 429 уходил без лишних заголовков
app.add_middleware(IPRateLimitMiddleware)

# CORS — разрешаем запросы от Telegram WebApp
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем API-роуты (/miniapp/api/*)
app.include_router(router)

# Раздаём фронтенд Mini App из папки webapp/ по пути /miniapp
# Монтируем ПОСЛЕ роутов, чтобы /miniapp/api/* перехватывался роутами первым
app.mount("/miniapp", StaticFiles(directory="webapp", html=True), name="webapp")
