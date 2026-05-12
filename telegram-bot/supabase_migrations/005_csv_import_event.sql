-- Migration 005: добавить csv_import в список разрешённых типов событий

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
    'reminder_sent',
    'export_csv',
    'csv_import'
));
