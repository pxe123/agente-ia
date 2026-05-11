-- 019_billing_pending_plan_change.sql
-- Mudança de plano agendada: usada para downgrade no fim do período atual.

alter table public.clientes
  add column if not exists billing_pending_plan_key text,
  add column if not exists billing_pending_plan_change_at timestamptz,
  add column if not exists billing_pending_plan_change_type text;

create index if not exists clientes_billing_pending_plan_change_idx
  on public.clientes (billing_pending_plan_change_at)
  where billing_pending_plan_key is not null;

