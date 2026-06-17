# Contrato — Confirmação de Agendamento (Agendamento IA ↔ ZapAction)

## Snapshot tenant

Campo `clinic` no evento `zapaction.scheduling.tenant_snapshot`:

```json
{
  "confirmation_policy": "auto",
  "confirmation_pending_ttl_hours": 48
}
```

## Webhooks Agenda → ZapAction

| Evento | Efeito |
|--------|--------|
| `appointment.pending` | UPSERT `status=pending` |
| `appointment.confirmed` | UPSERT `status=confirmed` |
| `appointment.rejected` | UPSERT `status=cancelled` + `meta.cancellation_reason=professional_rejected` |
| `appointment.proposal.created` | Ack 200 (espelho V2) |
| `appointment.proposal.resolved` | Ack 200 (espelho V2) |

## APIs Agenda (iniciadas no painel ZapAction)

Para marcações com `external_agenda_appointment_id`:

- `POST {AGENDA}/v1/appointments/{ext_id}/confirm`
- `POST {AGENDA}/v1/appointments/{ext_id}/reject`
- `POST {AGENDA}/v1/appointments/{ext_id}/propose`

## Ocupação de slots

Marcações `pending` devem bloquear slots (como `confirmed`), excluindo apenas `cancelled`.
