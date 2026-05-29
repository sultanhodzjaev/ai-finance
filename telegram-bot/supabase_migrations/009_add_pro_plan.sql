-- 009_add_pro_plan.sql
-- В код добавили тариф Pro ($10/мес), но constraint users_plan_check остался
-- от миграции 002 со whitelist'ом {trial, free, basic, premium}.
-- Polling lava-poll-invoices каждую минуту падал с
-- "violates check constraint users_plan_check" и спамил уведомления.

alter table users
  drop constraint if exists users_plan_check;

alter table users
  add constraint users_plan_check
  check (plan in ('trial', 'free', 'basic', 'premium', 'pro'));
