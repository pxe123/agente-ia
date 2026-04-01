-- Plans + entitlements + trial (SaaS self-serve)

-- 1) plans: fonte de verdade de preço/trial/entitlements
create table if not exists public.plans (
  plan_key text primary key,
  name text not null,
  price numeric not null default 0,
  currency text not null default 'BRL',
  trial_days int not null default 7,
  active boolean not null default true,
  entitlements_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- 2) clientes: colunas para trial e billing (se já existirem, ignora)
alter table public.clientes add column if not exists billing_plan_key text;
alter table public.clientes add column if not exists billing_status text;
alter table public.clientes add column if not exists billing_current_period_end timestamptz;
alter table public.clientes add column if not exists mp_customer_id text;
alter table public.clientes add column if not exists mp_preapproval_id text;
alter table public.clientes add column if not exists trial_ends_at timestamptz;

-- 3) billing_events: idempotência
create table if not exists public.billing_events (
  event_id text primary key,
  request_id text,
  resource_type text,
  data_id text,
  raw_body text,
  received_at timestamptz not null default now(),
  processed_at timestamptz,
  status text not null default 'received'
);

-- 4) seed inicial de planos (ajuste valores e entitlements)
insert into public.plans(plan_key, name, price, currency, trial_days, active, entitlements_json)
values
  ('social', 'Social', 49.90, 'BRL', 7, true, '{"whatsapp":true,"instagram":false,"messenger":false,"site":true,"exports":false,"chatbots":true,"usuarios_setores":false}'::jsonb),
  ('profissional', 'Profissional', 99.90, 'BRL', 7, true, '{"whatsapp":true,"instagram":true,"messenger":true,"site":true,"exports":true,"chatbots":true,"usuarios_setores":true}'::jsonb),
  ('empresa', 'Empresa', 199.90, 'BRL', 14, true, '{"whatsapp":true,"instagram":true,"messenger":true,"site":true,"exports":true,"chatbots":true,"usuarios_setores":true}'::jsonb)
on conflict (plan_key) do nothing;

