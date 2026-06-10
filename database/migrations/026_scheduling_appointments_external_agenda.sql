-- Idempotência webhook Agendamento IA → ZapAction (ver docs/plano_tecnico_continuacao_zapaction_agenda.md).
alter table public.scheduling_appointments
  add column if not exists external_agenda_appointment_id text;

comment on column public.scheduling_appointments.external_agenda_appointment_id is
  'UUID do appointment no serviço Agendamento IA (chave natural para upsert do webhook).';

create unique index if not exists uq_scheduling_appt_cliente_external_agenda
  on public.scheduling_appointments (cliente_id, external_agenda_appointment_id)
  where external_agenda_appointment_id is not null
    and length(trim(external_agenda_appointment_id)) > 0;
