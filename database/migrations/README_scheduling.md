# Migrações — módulo Agenda (ZapAction)

Aplicar no Supabase SQL Editor **nesta ordem**:

1. `025_scheduling_module.sql` — tabelas `scheduling_*`
2. `026_scheduling_appointments_external_agenda.sql` — `external_agenda_appointment_id` (webhook Agendamento IA)

Relacionadas ao onboarding (se ainda não aplicadas):

- `023_onboarding_funnel.sql`
- `024_billing_snapshots_onboarding.sql`

Após aplicar, validar integração: [`docs/agendamento_ia_integracao_checklist.md`](../../docs/agendamento_ia_integracao_checklist.md).
