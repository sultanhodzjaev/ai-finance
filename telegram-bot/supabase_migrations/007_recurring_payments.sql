-- Migration 007: регулярные платежи

create table if not exists recurring_payments (
    id           uuid primary key default gen_random_uuid(),
    telegram_id  bigint not null references users(telegram_id) on delete cascade,
    type         text not null default 'expense' check (type in ('expense', 'income')),
    amount       numeric(12, 2) not null check (amount > 0),
    category     text not null default 'other',
    description  text not null default '',
    period_days  integer not null check (period_days >= 1 and period_days <= 365),
    next_run_at  timestamptz not null,
    last_run_at  timestamptz,
    active       boolean not null default true,
    created_at   timestamptz not null default now()
);

create index if not exists idx_recurring_due
    on recurring_payments(next_run_at) where active = true;

create index if not exists idx_recurring_user
    on recurring_payments(telegram_id);

alter table recurring_payments disable row level security;
