-- Migration 008: список заблокированных пользователей

create table if not exists banned_users (
    telegram_id  bigint primary key references users(telegram_id) on delete cascade,
    reason       text not null default '',
    banned_at    timestamptz not null default now(),
    banned_by    bigint
);

alter table banned_users disable row level security;
