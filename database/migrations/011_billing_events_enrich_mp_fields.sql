-- Enriquecimento dos eventos de billing com campos relevantes do Mercado Pago
-- (fonte de verdade: webhook -> preapproval)

alter table public.billing_events
  add column if not exists mp_status text;

alter table public.billing_events
  add column if not exists plan_key text;

alter table public.billing_events
  add column if not exists next_payment_date timestamptz;

alter table public.billing_events
  add column if not exists amount numeric;

alter table public.billing_events
  add column if not exists currency text;

