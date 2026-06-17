# Contrato — Recorrência e booking painel (ZapAction ↔ Agendamento IA)

`request_schema_version`: **1**

A recorrência é **sempre** gerida no ZapAction (`scheduling_recurrence_series`). O Agendamento IA recebe apenas marcações atómicas (ocorrências), nunca expande séries.

## Autenticação

Mesmo esquema de `tenant-snapshot`: `Authorization: Bearer <AGENDAMENTO_IA_CLINIC_SYNC_API_KEY>`.

## 1. Criar ocorrência (painel → motor)

**`POST {AGENDA}/v1/integrations/zapaction/appointments`**

### Request

```json
{
  "request_schema_version": 1,
  "event_id": "za-book-<uuid>",
  "cliente_id": "<uuid>",
  "zapaction_appointment_id": "<uuid>",
  "recurrence": {
    "series_id": "<uuid>",
    "occurrence_at": "2026-06-16T13:00:00+00:00",
    "is_exception": false
  },
  "booking": {
    "service_id": "<uuid>",
    "provider_id": "<uuid|null>",
    "starts_at": "2026-06-16T13:00:00+00:00",
    "ends_at": "2026-06-16T13:30:00+00:00",
    "status": "confirmed",
    "contact": { "name": "Maria", "phone": "+5511999999999" },
    "notes": "",
    "metadata": { "source": "panel_recurrence" }
  }
}
```

Para agendamento **único** no painel, omitir `recurrence` ou enviar `recurrence: null`.

### Response 200

```json
{
  "request_schema_version": 1,
  "appointment_id": "<agenda_uuid>",
  "status": "confirmed"
}
```

### Idempotência

Chave `(cliente_id, zapaction_appointment_id)`. Reenvio com o mesmo par devolve o mesmo `appointment_id` sem duplicar slot.

### Erros (corpo JSON)

| code | HTTP | Significado |
|------|------|-------------|
| `slot_ocupado` | 409 | Intervalo indisponível |
| `servico_invalido` | 400 | `service_id` desconhecido/inativo |
| `provider_invalido` | 400 | `provider_id` inválido para o serviço |
| `tenant_nao_encontrado` | 404 | `cliente_id` sem tenant |
| `payload_invalido` | 400 | Schema inválido |

## 2. Cancelar em lote (série)

**`POST {AGENDA}/v1/integrations/zapaction/appointments/cancel-batch`**

```json
{
  "request_schema_version": 1,
  "event_id": "za-cancel-batch-<uuid>",
  "cliente_id": "<uuid>",
  "scope": "following",
  "series_id": "<zapaction_series_uuid>",
  "from_starts_at": "2026-06-16T13:00:00+00:00",
  "appointment_ids": []
}
```

| scope | Comportamento |
|-------|---------------|
| `following` | Cancela ocorrências da série com `starts_at >= from_starts_at` |
| `all` | Cancela todas as ocorrências da série no motor |
| `ids` | Cancela apenas `appointment_ids` (IDs do Agenda) |

Response 200:

```json
{
  "request_schema_version": 1,
  "cancelled": 3,
  "appointment_ids": ["...", "..."]
}
```

Cancelamento **unitário** continua via `POST /v1/agendamento` com `operation: cancel` (já implementado no ZapAction).

## 3. Webhook reverso (extensão)

Eventos `appointment.*` podem incluir campos opcionais:

```json
{
  "zapaction_appointment_id": "<uuid>",
  "recurrence": {
    "series_id": "<uuid>",
    "occurrence_at": "2026-06-16T13:00:00+00:00"
  }
}
```

O receptor ZapAction preenche `recurrence_series_id` e `series_occurrence_at` quando presentes.

## 4. Export / reconciliação

`GET /v1/integrations/zapaction/appointments/export` deve incluir nos items (opcional):

- `zapaction_appointment_id`
- `recurrence.series_id`
- `recurrence.occurrence_at`

## 5. Ocupação de slots

Marcações criadas pelo painel com `status: confirmed` bloqueiam slots no motor como qualquer outra marcação confirmada.

## 6. Feature flag (deploy gradual)

No ZapAction: `RECURRENCE_EXTERNAL_SYNC_ENABLED` (env) ou ausência de API no Agenda → materialização local com `meta.motor_sync=pending` até o motor responder.
