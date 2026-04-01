-- Liga eventos de billing ao cliente (histórico por cliente_id + retrocompat com data_id = preapproval)

alter table public.billing_events
  add column if not exists cliente_id uuid references public.clientes(id) on delete set null;

create index if not exists billing_events_cliente_id_idx on public.billing_events (cliente_id);
create index if not exists billing_events_status_processed_idx on public.billing_events (status, processed_at desc);
