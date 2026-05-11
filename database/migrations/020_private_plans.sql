-- 020_private_plans.sql
-- Planos exclusivos: visíveis e contratáveis somente por um cliente específico.

alter table public.plans
  add column if not exists is_private boolean not null default false,
  add column if not exists private_cliente_id uuid references public.clientes(id) on delete set null;

create index if not exists plans_private_cliente_id_idx
  on public.plans (private_cliente_id)
  where is_private = true;

create index if not exists plans_public_active_price_idx
  on public.plans (active, price)
  where is_private = false;

