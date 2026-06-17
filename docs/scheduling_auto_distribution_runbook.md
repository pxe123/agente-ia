# Runbook: Distribuição Automática na Agenda (V1)

## Resumo

Modo opcional por tenant em que o cliente escolhe **serviço + horário** e o sistema atribui o profissional (round-robin). Coexiste com o modo **manual** (comportamento anterior).

- **Escopo V1:** motor interno `zapaction_internal` apenas
- **Default:** `manual` (zero impacto em tenants existentes)
- **Config:** painel → Agenda → aba Clínica → «Atribuição de profissional»

## Pré-requisitos

1. Migration `029_professional_assignment_mode.sql` aplicada no Supabase
2. Tenant com `scheduling_engine = zapaction_internal`
3. Pelo menos 2 profissionais activos (para testar round-robin) ou 1 (degrada para fluxo sem escolha)

## Activar piloto

1. Admin: confirmar motor interno no tenant (`PATCH /admin/api/.../scheduling-engine` ou BD)
2. Painel cliente: Agenda → Clínica → **Distribuição automática** → Guardar
3. Validar:

```bash
python scripts/verify_auto_distribution_pilot.py --cliente-id <UUID>
```

4. Smoke:
   - Página pública `/agenda/<slug>`: sem dropdown de profissional; horários unificados
   - WhatsApp: fluxo sem passo «escolha profissional»
   - Painel: badge **Auto** em novas marcações; acção **Profissional** para reatribuir

## Rollback (sem deploy)

1. Painel → Clínica → **Cliente escolhe profissional** → Guardar  
   ou SQL: `UPDATE scheduling_settings SET professional_assignment_mode = 'manual' WHERE cliente_id = '...'`
2. Cursor round-robin é limpo ao voltar a `manual`

## Limitações V1

| Item | Nota |
|------|------|
| Motor `agendamento_ia` | UI desactiva opção; `uses_auto_distribution` retorna false |
| Estratégia `least_busy` | Reservada V2; activo só `round_robin` |
| Race em slot popular | Retry com próximo candidato; mensagem «horário acabou de ser ocupado» |
| Sync Agendamento IA | Sem alteração; modo auto não sincroniza política externa |

## Monitorização

- Marcações com `meta.assignment_mode = 'auto'` e `meta.assigned_by = 'system'`
- `distribution_last_professional_id` em `scheduling_settings` (cursor round-robin)
- Logs de `book_with_auto_assignment` / `slot_ocupado` em picos de tráfego

## Testes

```bash
python -m unittest tests.test_scheduling_assignment tests.test_scheduling_pool_slots -v
```

## Ficheiros principais

- `database/migrations/029_professional_assignment_mode.sql`
- `services/scheduling/pool_slots.py`, `assignment.py`, `bookings.py`
- `panel/routes/public.py`, `panel/templates/agenda_publica.html`
- `panel/routes/scheduling.py`, `panel/templates/scheduling/wizard.html`
- `services/scheduling/service.py` (WhatsApp)
