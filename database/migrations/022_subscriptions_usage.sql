-- 022_subscriptions_usage.sql
-- Fonte de verdade para assinatura por tenant + base para usage.

-- subscriptions: 1 assinatura ativa por cliente (tenant), com histórico opcional por updates.
create extension if not exists pgcrypto;

create table if not exists public.subscriptions (
  id uuid primary key default gen_random_uuid(),
  cliente_id uuid not null,
  provider text not null default 'mercadopago',
  provider_subscription_id text,
  plan_key text,
  status text,
  current_period_end timestamptz,
  trial_ends_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists subscriptions_cliente_unique on public.subscriptions (cliente_id);
create index if not exists subscriptions_status_idx on public.subscriptions (status);

-- usage diário (base mínima; pode evoluir por feature)
create table if not exists public.tenant_usage_daily (
  cliente_id uuid not null,
  day date not null,
  messages_count int not null default 0,
  conversations_count int not null default 0,
  leads_count int not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (cliente_id, day)
);

