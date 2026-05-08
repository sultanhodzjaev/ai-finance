# AI-Финансист — Telegram Bot + Mini App

Telegram-бот с AI для учёта личных трат и доходов + Telegram Mini App с визуальным дашбордом.

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
- **Хранилище:** Supabase (PostgreSQL) — данные сохраняются между перезапусками

## Where things live

```
telegram-bot/
├── main.py                 # Точка входа: asyncio.gather(bot + FastAPI), init_db()
├── handlers/
│   ├── start.py            # /start — главное меню с кнопкой Mini App
│   ├── transactions.py     # Запись трат и доходов (текст + фото)
│   ├── stats.py            # /today, /stats — доходы и расходы отдельно
│   └── ai_advisor.py       # /ask — вопросы финансисту
├── services/
│   ├── gemini.py           # Gemini API: категоризация + определение типа (доход/расход)
│   └── storage.py          # Supabase PostgreSQL — CRUD для пользователей и транзакций
├── api/
│   ├── server.py           # FastAPI app + CORS + static mount
│   ├── routes.py           # REST: /miniapp/api/me, /transactions, /stats, /categories
│   └── auth.py             # Валидация Telegram initData (HMAC-SHA256)
├── webapp/
│   ├── index.html          # SPA shell (скрипты в конце body, статический лоадер)
│   ├── app.js              # Вся логика: дашборд, история, форма, bottom sheet
│   └── style.css           # Кастомные стили
├── utils/
│   ├── categories.py       # CATEGORIES (расходы) + INCOME_CATEGORIES (доходы)
│   └── formatters.py       # Форматирование сумм
└── supabase_schema.sql     # SQL-схема для Supabase Dashboard
```

## Architecture decisions

- **Один процесс** для бота и FastAPI (`asyncio.gather`)
- **Gemini через httpx** (не SDK) — прямые REST-вызовы, asyncio-совместимо
- **Модель `gemini-2.5-flash`** — `gemini-2.0-flash` недоступна для этого ключа (404)
- **UUID для транзакций** — каждая запись получает `id` при создании
- **Supabase service_role ключ** — обходит RLS, правильно для серверного приложения
- **Валидация initData** обязательна на каждом endpoint

## Product

- Запись трат/доходов текстом → Gemini определяет тип и категорию → подтверждение
- Распознавание чеков по фото (всегда расход)
- Вопросы финансисту: /ask или кнопка в меню
- `/today` — доходы и расходы за день с остатком
- `/stats` — статистика за месяц с остатком
- **Mini App:** 3-карточный дашборд (доходы/расходы/остаток), 2 диаграммы, история с фильтрами по типу и периоду, добавление/редактирование/удаление

## User preferences

- Язык интерфейса: русский
- Валюта по умолчанию: KGS (кыргызский сом)
- Комментарии в коде: на русском

## Secrets (Replit Secrets)

| Ключ | Назначение |
|---|---|
| `BOT_TOKEN` | Telegram Bot API токен |
| `GEMINI_API_KEY` | Google Gemini API ключ |
| `SESSION_SECRET` | Секрет сессий |
| `SUPABASE_URL` | URL Supabase проекта |
| `SUPABASE_KEY` | anon public ключ Supabase |
| `SUPABASE_SERVICE_KEY` | service_role ключ (используется в боте) |

## Gotchas

- Gemini `gemini-2.0-flash` → 404 для этого ключа; используй `gemini-2.5-flash`
- Mini App требует HTTPS — на Replit это автоматически через `*.replit.dev`
- Workflow для Mini App: `artifacts/api-server: Telegram Mini App`
- FastAPI маршруты используют префикс `/miniapp/api/` — статика монтируется после роутов
- Supabase: используй `service_role` ключ (обходит RLS), не `anon` ключ
- SQL-схема: `telegram-bot/supabase_schema.sql` — применяется один раз через SQL Editor

## Pointers

- API spec: `telegram-bot/api/routes.py`
- Категории: `telegram-bot/utils/categories.py`
- Хранилище: `telegram-bot/services/storage.py`
- SQL-схема: `telegram-bot/supabase_schema.sql`
