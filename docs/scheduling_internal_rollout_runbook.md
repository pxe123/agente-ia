# Rollout motor interno de agendamento (P0 + config por tenant)

Promove `services/scheduling/` como agenda oficial por tenant.

**Fonte definitiva (v2):** `scheduling_settings.scheduling_engine` (`agendamento_ia` | `zapaction_internal`).  
Alteração via **Admin → Clientes** ou `PATCH /admin/api/clientes/<id>/scheduling-engine` — sem restart.

Migration: `database/migrations/028_scheduling_engine.sql`  
Resolver: `services/scheduling/engine.py`

## Variáveis de ambiente (legado / break-glass)

| Variável | Efeito |
|----------|--------|
| `scheduling_engine` na BD | **Fonte definitiva** por tenant |
| `SCHEDULING_INTERNAL_CLIENTE_IDS` | Rede de segurança (fallback se BD falhar). Manter 2 semanas pós-deploy; depois esvaziar (Fase 3) |
| `SCHEDULING_FORCE_AGENDA_CLIENTE_IDS` | Break-glass — força Agenda |
| `USE_INTERNAL_SCHEDULING=0` | Padrão produção |
| `USE_INTERNAL_SCHEDULING=1` | Global legado (deprecar) |

Código: `scheduling_uses_internal_motor()` → `services/scheduling/engine.py`.

### Fases depreciação allowlist .env

| Fase | Acção |
|------|--------|
| 1 — Deploy | BD decide; **manter** allowlist no `.env` |
| 2 — 2 semanas | Monitorizar; novos tenants só via admin |
| 3 — Limpeza | Esvaziar `SCHEDULING_INTERNAL_CLIENTE_IDS` |

Script backfill: `python3 scripts/migrate_env_allowlist_to_db.py`

## Ordem de rollout (Etapas 1–6)

### Etapa 1 — Deploy com flags vazias

```env
USE_INTERNAL_SCHEDULING=0
SCHEDULING_INTERNAL_CLIENTE_IDS=
SCHEDULING_FORCE_AGENDA_CLIENTE_IDS=
```

Sem impacto em clientes existentes.

### Etapa 2–3 — Código + testes (sem ativar)

- `scheduling_uses_internal_motor(cliente_id)` implementado
- Links `/agenda/{slug}` em `PUBLIC_MARKETING_PREFIXES`
- Cancel `operation=cancel` no `handle_turn`
- Testes: `tests/test_scheduling_internal_motor.py`, `tests/test_scheduling_cancel_turn.py`

```bash
python -m unittest tests.test_scheduling_internal_motor tests.test_scheduling_cancel_turn tests.test_agendamento_ia_urls -v
python scripts/verify_agendamento_ia_env.py
```

### Etapa 4 — Tenant piloto (NOVO)

**Gate obrigatório:** usar apenas tenant **sem histórico no PostgreSQL do Agenda**.

- Conta criada após deploy do motor interno
- Nunca teve marcações só no Agenda (webhook falhou / export antigo)
- Definir `scheduling_engine=zapaction_internal` no admin (ou allowlist env durante Fase 1)

### Etapa 5 — Smoke piloto

Checklist manual no tenant piloto:

1. **Configurar agenda** — serviços, profissionais, horários, slug público
2. **Fluxo WhatsApp** — nó `agendamento_ia` cria marcação em `scheduling_appointments` (sem linha nova no Agenda PG)
3. **Cancelar conversa** — `operation: cancel` ou painel → status `cancelled` no Supabase
4. **Remarcar** — painel Agenda → novo horário
5. **Link** — URL `{PUBLIC_BASE_URL}/agenda/{slug}` (não `/v1/book/...`)
6. **Painel** — marcações visíveis; origem `zapaction_local`

Rollback imediato: admin PATCH → `agendamento_ia` (sem restart). Emergência: `SCHEDULING_FORCE_AGENDA_CLIENTE_IDS`.

### Etapa 6 — Clientes reais (com histórico Agenda)

**Não** entrar na allowlist sem:

1. Painel → **Sincronizar do Agendamento IA** ou `sync_appointments_from_agenda(cliente_id, since_days=90)`
2. Auditoria:

```bash
python scripts/audit_scheduling_mirror.py <cliente_uuid>
```

3. SQL Supabase (ajustar `cliente_id`):

```sql
SELECT count(*) FROM scheduling_appointments
WHERE cliente_id = '<uuid>' AND external_agenda_appointment_id IS NOT NULL;

SELECT count(*) FROM scheduling_appointments
WHERE cliente_id = '<uuid>' AND external_agenda_appointment_id IS NULL;

SELECT id, starts_at, status, external_agenda_appointment_id
FROM scheduling_appointments
WHERE cliente_id = '<uuid>' AND status != 'cancelled' AND starts_at > now()
ORDER BY starts_at;
```

4. Comparar export vs espelhadas; resolver gaps antes da allowlist
5. Só então PATCH admin → `zapaction_internal` (ou backfill script)

## Riscos conhecidos (auditoria dados)

| Cenário | Risco |
|---------|-------|
| Piloto novo | Nenhum |
| Cliente real sem import | Marcações só no Agenda PG invisíveis no painel |
| Motor interno ativo | Novas marcações só no Supabase (esperado) |
| Rollback FORCE_AGENDA | Volta a criar no Agenda; marcações internas ficam no Supabase |

**Não alterar no P0:** Google OAuth, webhooks, sync snapshot, importadores — continuam para clientes Agenda.

## P2 — Diferencial comercial (implementado)

| Item | Onde |
|------|------|
| Calendário dia/semana/mês | `/painel/agenda/calendario` |
| Drag-and-drop remarcar | Calendário (marcações locais) → `POST /painel/agenda/api/appointment/reschedule` |
| Dashboard stats | Cards no topo do calendário (hoje, semana, 24h, canceladas) |
| Filtros na lista | Aba Agendamentos: estado, profissional, pesquisa |
| Lembretes WhatsApp | `SCHEDULING_REMINDERS_ENABLED=1` + cron `scripts/run_scheduling_reminders.py` |
| Race em booking | Revalidação pós-insert em `book_appointment` |

**Lembretes (produção):**
```env
SCHEDULING_REMINDERS_ENABLED=1
SCHEDULING_REMINDER_HOURS_BEFORE=24,1
```
Cron a cada 15 min: `python scripts/run_scheduling_reminders.py`

## P1 — Produto (implementado)

| Item | Onde |
|------|------|
| Página pública com serviço + profissional | `/agenda/<slug>`, `agenda_publica.html` |
| Bloqueios de agenda | Painel → Horários → «Bloqueios de agenda» |
| Remarcação no painel | Painel → Agendamentos → «Remarcar» (marcações locais) |
| Migração Agenda → Supabase | `python scripts/migrate_scheduling_from_agenda.py <uuid>` |

## Referências

- `services/scheduling/service.py` — `handle_turn`
- `services/agendamento_ia_link.py` — URLs públicas
- `scripts/audit_scheduling_mirror.py` — gate antes de `zapaction_internal`
- `scripts/migrate_env_allowlist_to_db.py` — backfill env → BD
- Plano auditoria: `.cursor/plans/auditoria_dados_agenda_vs_interno_6a460115.plan.md`
