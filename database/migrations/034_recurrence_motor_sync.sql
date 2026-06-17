-- Índice para job de retry de sync motor externo (recorrência / booking painel).

create index if not exists idx_scheduling_appointments_motor_sync_pending
  on public.scheduling_appointments (cliente_id, updated_at)
  where (meta->>'motor_sync') = 'pending';
