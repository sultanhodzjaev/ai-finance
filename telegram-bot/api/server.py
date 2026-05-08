from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes import router

app = FastAPI(title="AI-финансист Mini App")

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
