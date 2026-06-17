# Runbook — Confirmação de Agendamento

## Visão geral

Política tenant-wide em `scheduling_settings.confirmation_policy`:

| Valor | Comportamento |
|-------|---------------|
| `auto` (default) | `status=confirmed` imediato — igual ao comportamento anterior |
| `professional` | `status=pending` até aprovação no painel ou WhatsApp do profissional |
| `reception` | Reservado V2 — UI desactivada, fallback `auto` |

**V1:** apenas motor interno (`zapaction_internal`). Tenants com Agenda externa não podem activar `professional`.

## Migration

```bash
# Aplicar no Supabase
database/migrations/030_confirmation_policy.sql
database/migrations/031_confirmation_resolve_proposal.sql
```

## WhatsApp — alertas

### Pedido pendente (clínica)

Quando `confirmation_policy=professional` e o cliente marca um horário, o sistema envia WhatsApp via `notify_pending_booking`:

1. **Destino preferido:** `clientes.notify_whatsapp` (recepção/admin — configurável no admin do tenant).
2. **Fallback:** `scheduling_professionals.whatsapp_notify_phone` do profissional atribuído.
3. **Conteúdo:** cliente, serviço, profissional, horário e URL completa do painel (`/painel/agenda?tab=agendamentos&status=pending`).

Se nenhum número estiver configurado, o booking mantém-se `pending` mas não há alerta (registo em log).

### Proposta de novo horário (cliente)

Quando a clínica usa **Sugerir horário** no painel, o cliente recebe **um único link** (`/confirmacao/{token}`). Na página escolhe Aceitar ou Recusar.

- Token novo: `action=resolve_proposal` (migration 031).
- Links antigos com dois tokens (`accept_proposal` / `decline_proposal`) continuam válidos até expirarem.

## Piloto homologação

Tenant: `clinica-teste` (`d1ddf96e-e667-48dc-9975-362a9c539fe2`)

```bash
# Ubuntu: use python3 (não há alias `python` por defeito)
python3 scripts/verify_confirmation_policy_pilot.py
python3 scripts/verify_confirmation_policy_pilot.py --cliente-id d1ddf96e-e667-48dc-9975-362a9c539fe2
```

### Activar piloto

1. Admin → definir `notify_whatsapp` no tenant (recepção) **ou** Profissionais → **WhatsApp alertas confirmação**
2. Painel → Agenda → Configuração → opções avançadas → **Profissional aprova antes** → Guardar
3. Agendar via `/agenda/<slug>` ou WhatsApp — deve mostrar «Aguardando confirmação»
4. Clínica/profissional recebe WhatsApp com link do painel
5. Painel → Agendamentos → filtro **Pendente** → Confirmar / Sugerir / Recusar
6. Sugerir horário → cliente recebe **1 link**; aceitar confirma, recusar cancela

## Job TTL

```bash
python3 -c "from services.jobs.confirmation_pending_expiry import run_confirmation_pending_expiry; print(run_confirmation_pending_expiry())"
```

Agendar em cron (ex.: hora a hora).

## Rollback

1. Painel → Clínica → **Confirmação automática** → Guardar  
   ou SQL: `UPDATE scheduling_settings SET confirmation_policy='auto' WHERE cliente_id='...'`
2. Pedidos `pending` existentes: confirmar ou cancelar manualmente no painel

## Contrato Agendamento IA (V2)

Snapshot (`agendamento_ia_sync.py`):

```json
"clinic": {
  "confirmation_policy": "auto|professional",
  "confirmation_pending_ttl_hours": 48
}
```

Webhooks aceites: `appointment.pending`, `appointment.confirmed`, `appointment.rejected`, `appointment.proposal.*`

APIs proxy painel → Agenda (futuro): `POST /v1/appointments/{id}/confirm|reject|propose`
