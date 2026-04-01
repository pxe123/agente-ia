-- Financeiro (métricas diárias) + dedupe de notificações

create table if not exists public.billing_snapshots_daily (
  day date primary key,
  mrr_total numeric not null default 0,
  active_subscriptions int not null default 0,
  trialing int not null default 0,
  past_due int not null default 0,
  canceled int not null default 0,
  inactive int not null default 0,
  new_paid int not null default 0,
  churned int not null default 0,
  revenue_estimated numeric not null default 0,
  by_plan jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.customer_notifications (
  id bigserial primary key,
  cliente_id text not null,
  type text not null,
  day date not null,
  channel text not null default 'whatsapp',
  status text not null default 'sent',
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (cliente_id, type, day)
);

-- Número para notificações de cobrança (WhatsApp do dono da conta)
alter table public.clientes add column if not exists notify_whatsapp text;

