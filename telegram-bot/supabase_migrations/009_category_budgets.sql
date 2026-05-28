-- Migration 009: бюджеты на расходные категории
-- Юзер ставит месячный лимит на категорию (например, «Еда 30000 KGS»);
-- бот шлёт пуш при пересечении 80% и 100% за календарный месяц.

create table if not exists category_budgets (
    id              uuid primary key default gen_random_uuid(),
    telegram_id     bigint not null references users(telegram_id) on delete cascade,
    category        text not null,
    monthly_limit   numeric(12, 2) not null check (monthly_limit > 0),
    currency        text not null default 'KGS',
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    -- один бюджет на категорию у юзера; UPSERT через ON CONFLICT
    unique (telegram_id, category)
);

create index if not exists idx_category_budgets_user
    on category_budgets(telegram_id);

alter table category_budgets disable row level security;
