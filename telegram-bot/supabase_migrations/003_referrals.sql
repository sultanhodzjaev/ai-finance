-- Migration 003: реферальная программа
-- Прогнать в Supabase Dashboard → SQL Editor → New query → Run

-- 1. Колонки реферала
alter table users
  add column if not exists referral_code        text unique,
  add column if not exists referred_by_user_id  bigint references users(telegram_id);

-- 2. Сгенерировать код для существующих юзеров без кода
update users
   set referral_code = lower(substr(md5(telegram_id::text || extract(epoch from now())::text), 1, 8))
 where referral_code is null;

-- 3. Новые типы событий для аналитики реферала
alter table events drop constraint if exists events_type_check;
alter table events add constraint events_type_check check (type in (
    'ai_question',
    'limit_hit',
    'upgrade_clicked',
    'trial_warned',
    'trial_expired',
    'subscription_paid',
    'subscription_expired',
    'subscription_extended',
    'referral_invited',
    'referral_redeemed',
    'reminder_sent'
));

-- 4. Индекс для быстрого поиска по реф-коду
create index if not exists idx_users_referral_code on users(referral_code);
