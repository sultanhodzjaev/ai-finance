-- Migration 006: кастомные категории пользователя

create table if not exists custom_categories (
    id           uuid primary key default gen_random_uuid(),
    telegram_id  bigint not null references users(telegram_id) on delete cascade,
    name         text not null,
    emoji        text not null default '📦',
    type         text not null check (type in ('expense', 'income')),
    created_at   timestamptz not null default now()
);

create index if not exists idx_custom_categories_user
    on custom_categories(telegram_id);

-- RLS — служебная таблица, доступна только service_role
alter table custom_categories disable row level security;
