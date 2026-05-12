-- Migration 002: подписки и лимиты
-- Прогнать в Supabase Dashboard → SQL Editor → New query → вставить → Run

-- 1. Колонки плана в users
alter table users
  add column if not exists plan text not null default 'trial'
    check (plan in ('trial', 'free', 'basic', 'premium')),
  add column if not exists trial_until        timestamptz default (now() + interval '7 days'),
  add column if not exists subscription_until timestamptz,
  add column if not exists trial_warned_at    timestamptz,
  add column if not exists trial_expired_at   timestamptz;

-- 2. Существующим пользователям выставляем триал с момента миграции
update users
   set trial_until = now() + interval '7 days',
       plan        = 'trial'
 where trial_until is null;

-- 3. Бессрочный премиум владельцу (Акмаль)
update users
   set plan = 'premium',
       subscription_until = null
 where telegram_id = 5557488294;

-- 4. Таблица событий (для подсчёта лимитов и аналитики)
create table if not exists events (
    id          bigserial primary key,
    telegram_id bigint not null references users(telegram_id) on delete cascade,
    type        text   not null check (type in (
        'ai_question',
        'limit_hit',
        'upgrade_clicked',
        'trial_warned',
        'trial_expired',
        'subscription_paid',
        'subscription_expired'
    )),
    metadata    jsonb not null default '{}',
    created_at  timestamptz not null default now()
);

create index if not exists idx_events_user_type_time
    on events(telegram_id, type, created_at desc);

-- 5. RLS — служебная таблица, доступна только service_role
alter table events disable row level security;
