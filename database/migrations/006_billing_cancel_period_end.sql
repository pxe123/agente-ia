-- 006_billing_cancel_period_end.sql
-- Adiciona campos para cancelamento agendado (fim do período) na tabela clientes.

alter table if exists public.clientes
add column if not exists billing_cancel_at_period_end boolean default false;

alter table if exists public.clientes
add column if not exists billing_cancel_scheduled_at timestamptz;

