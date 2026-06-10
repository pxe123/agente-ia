-- 027_stripe_billing.sql
-- Stripe: suporte a assinaturas recorrentes (checkout + portal + webhook) em multi-tenant.

create extension if not exists pgcrypto;

-- 1) subscriptions: adicionar colunas Stripe (fonte de verdade por tenant)
alter table public.subscriptions add column if not exists user_id uuid;
alter table public.subscriptions add column if not exists stripe_customer_id text;
alter table public.subscriptions add column if not exists stripe_subscription_id text;
alter table public.subscriptions add column if not exists stripe_price_id text;
alter table public.subscriptions add column if not exists cancel_at_period_end boolean;

-- índice para lookup rápido por subscription/customer
create index if not exists subscriptions_stripe_sub_idx on public.subscriptions (stripe_subscription_id);
create index if not exists subscriptions_stripe_customer_idx on public.subscriptions (stripe_customer_id);

-- 2) clientes: campos Stripe (compat com UI e troubleshooting)
alter table public.clientes add column if not exists stripe_customer_id text;
alter table public.clientes add column if not exists stripe_subscription_id text;
alter table public.clientes add column if not exists stripe_price_id text;

-- 3) billing_events: permitir eventos Stripe (idempotência)
-- O esquema base já tem resource_type/data_id/raw_body/status/processed_at.
-- Para Stripe:
-- - event_id = stripe event.id
-- - resource_type = 'stripe'
-- - data_id = event.type
-- - raw_body = payload
-- cliente_id já existe via migração 010_billing_events_cliente_id.sql

