-- 029_plans_stripe_ids.sql
-- SaaS controla planos; Stripe Price/Product IDs persistidos por plan_key.

alter table public.plans add column if not exists stripe_price_id text;
alter table public.plans add column if not exists stripe_product_id text;

create index if not exists plans_stripe_price_id_idx
  on public.plans (stripe_price_id)
  where stripe_price_id is not null;

-- Backfill manual (após deploy): vincule Price IDs existentes por plan_key, ex.:
-- update public.plans set stripe_price_id = 'price_...' where plan_key = 'social';
-- Ou rode: python scripts/sync_plan_stripe_prices_from_env.py
