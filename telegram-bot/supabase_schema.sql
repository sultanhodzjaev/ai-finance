-- Схема базы данных AI-Финансист
-- Выполни этот SQL в Supabase Dashboard → SQL Editor → New query

-- Таблица пользователей
create table if not exists users (
    telegram_id bigint primary key,
    username    text    not null default '',
    first_name  text    not null default 'Друг',
    currency    text    not null default 'KGS',
    created_at  timestamptz not null default now()
);

-- Таблица транзакций
create table if not exists transactions (
    id          uuid primary key default gen_random_uuid(),
    telegram_id bigint not null references users(telegram_id) on delete cascade,
    type        text   not null default 'expense' check (type in ('expense', 'income')),
    amount      numeric(12, 2) not null check (amount > 0),
    category    text   not null default 'other',
    description text   not null default '',
    merchant    text,
    source      text   not null default 'text',
    created_at  timestamptz not null default now()
);

-- Индекс для быстрой выборки транзакций по пользователю
create index if not exists idx_transactions_telegram_id
    on transactions(telegram_id, created_at desc);

-- Row Level Security (отключаем — доступ только через service_role из бота)
alter table users        disable row level security;
alter table transactions disable row level security;
