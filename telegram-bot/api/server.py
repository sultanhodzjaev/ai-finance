import os
import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from api.routes import router
from api.webhooks import router as webhooks_router

# В проде /docs и /openapi.json торчат в интернет и раскрывают все эндпоинты,
# схемы и параметры — удобство для дев-окружения, лишний инфо-leak для атакующего.
# В dev оставляем (ENV=dev), на проде — None.
_IS_DEV = os.getenv("ENV", "prod").lower() == "dev"

app = FastAPI(
    title="AI-финансист Mini App",
    docs_url="/docs" if _IS_DEV else None,
    redoc_url="/redoc" if _IS_DEV else None,
    openapi_url="/openapi.json" if _IS_DEV else None,
)


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


class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    """
    Запрещает кэшировать HTML/JS/CSS Mini App. Telegram WebView держит файлы
    подолгу, и юзеры видят старую UI после деплоя. Для API-роутов кэш не трогаем.
    """
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/miniapp") and not path.startswith("/miniapp/api"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


app.add_middleware(NoCacheStaticMiddleware)

# Rate-limit раньше CORS, чтобы 429 уходил без лишних заголовков
app.add_middleware(IPRateLimitMiddleware)

# CORS — разрешаем запросы только с доверенных origin'ов. Раньше стояло "*",
# что давало любому стороннему сайту слать запросы к нашему API от имени юзера
# (если у злоумышленника есть валидный initData). Telegram WebApp на iOS/Android
# использует "https://web.telegram.org"; для Desktop и нашей собственной верстки
# Mini App на botfinance.xyz — добавлено отдельно. Доп. origin можно прокинуть
# через env ALLOWED_ORIGINS=...,... (запятая) — для миграции домена и стейджа.
_DEFAULT_ALLOWED_ORIGINS = [
    "https://web.telegram.org",
    "https://botfinance.xyz",
]
_extra_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
_ALLOWED_ORIGINS = _DEFAULT_ALLOWED_ORIGINS + _extra_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["X-Init-Data", "Content-Type"],
)

# Подключаем API-роуты (/miniapp/api/*) и внешние webhook'и (/webhook/*)
app.include_router(router)
app.include_router(webhooks_router)

# Раздаём фронтенд Mini App из папки webapp/ по пути /miniapp
# Монтируем ПОСЛЕ роутов, чтобы /miniapp/api/* перехватывался роутами первым
app.mount("/miniapp", StaticFiles(directory="webapp", html=True), name="webapp")
