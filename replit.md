# AI-Финансист — Telegram Bot + Mini App

Telegram-бот с AI для учёта личных трат + Telegram Mini App с визуальным дашбордом.

## Run & Operate

- **Telegram Bot + Mini App:** workflow `artifacts/api-server: Telegram Mini App`
  - Запускает aiogram-бот (polling) + FastAPI-сервер (порт 5000) в одном процессе
  - Команда: `cd /home/runner/workspace/telegram-bot && PYTHONIOENCODING=utf-8 LANG=C.UTF-8 python main.py`
- **API Server (Express, не используется ботом):** workflow `artifacts/api-server: API Server`
- Mini App доступен через прокси на пути `/miniapp`

## Stack

- **Бот:** Python 3.11, aiogram 3.x, FSM (MemoryStorage)
- **AI:** Gemini API (`gemini-2.5-flash`) через прямые httpx REST-вызовы
- **Mini App backend:** FastAPI + uvicorn (порт 5000)
- **Mini App frontend:** HTML5 + Tailwind CSS CDN + Chart.js CDN (без сборки)
- **Аутентификация Mini App:** HMAC-SHA256 проверка Telegram `initData`
- **Хранилище:** Python dict в памяти (общий для бота и Mini App, сбрасывается при рестарте)

## Where things live

```
telegram-bot/
├── main.py                 # Точка входа: asyncio.gather(bot + FastAPI)
├── handlers/
│   ├── start.py            # /start — главное меню с кнопкой Mini App
│   ├── transactions.py     # Запись трат (текст + фото)
│   ├── stats.py            # /today, /stats
│   └── ai_advisor.py       # /ask — вопросы финансисту
├── services/
│   ├── gemini.py           # Gemini API: категоризация текста и фото-чеков
│   └── storage.py          # In-memory хранилище + CRUD для транзакций
├── api/
│   ├── server.py           # FastAPI app + CORS + static mount
│   ├── routes.py           # REST: /miniapp/api/me, /transactions, /stats, /categories
│   └── auth.py             # Валидация Telegram initData (HMAC-SHA256)
├── webapp/
│   ├── index.html          # SPA shell
│   ├── app.js              # Вся логика: дашборд, история, форма, bottom sheet
│   └── style.css           # Кастомные стили (chart canvas, cat-btn, sheet animations)
└── utils/
    ├── categories.py       # 10 категорий с эмодзи
    └── formatters.py       # Форматирование сумм
```

## Architecture decisions

- **Один процесс** для бота и FastAPI (`asyncio.gather`) — хранилище в памяти общее без race conditions (GIL)
- **Gemini через httpx** (не SDK) — SDK не поддерживает asyncio корректно; прямые REST-вызовы надёжнее
- **Модель `gemini-2.5-flash`** — `gemini-2.0-flash` недоступна для новых аккаунтов (404)
- **UUID для транзакций** — каждая запись получает `id` при создании (и через бота, и через Mini App)
- **Валидация initData** обязательна на каждом endpoint — без неё чужие данные открыты

## Product

- Запись трат текстом: «потратил 500 на такси» → Gemini категоризирует → подтверждение
- Распознавание чеков по фото
- Вопросы финансисту: /ask или кнопка в меню
- Статистика за день/неделю/месяц
- **Mini App:** дашборд с диаграммами, история с фильтрами, добавление/редактирование/удаление трат

## User preferences

- Язык интерфейса: русский
- Валюта по умолчанию: KGS (кыргызский сом)
- Комментарии в коде: на русском

## Gotchas

- Данные в памяти — сбрасываются при перезапуске воркфлоу
- Gemini `gemini-2.0-flash` → 404 для этого ключа; используй `gemini-2.5-flash`
- Mini App требует HTTPS — на Replit это автоматически через `*.replit.dev`
- Workflow для Mini App: `artifacts/api-server: Telegram Mini App` (НЕ старый "Telegram Bot")
- FastAPI маршруты используют префикс `/miniapp/api/` — статика монтируется после роутов

## Pointers

- API spec: `telegram-bot/api/routes.py`
- Категории: `telegram-bot/utils/categories.py`
- Хранилище: `telegram-bot/services/storage.py`
