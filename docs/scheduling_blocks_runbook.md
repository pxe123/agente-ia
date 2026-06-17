# Runbook — Bloqueios de Horário (motor interno)

## Resumo

Bloqueios marcam intervalos **indisponíveis para novos agendamentos**. Não cancelam marcações já existentes. O campo `reason` é nota livre (almoço, reunião, feriado…) — o sistema **não classifica** motivos.

## Dois modos

| Modo | `professional_id` | Efeito |
|------|-------------------|--------|
| **Por profissional** | UUID | Só a agenda desse profissional fica indisponível |
| **Toda a clínica** | `null` | Todos os profissionais indisponíveis no intervalo |

Ambos entram em `busy_intervals_utc` (`services/scheduling/repository.py`) e afectam agenda pública, WhatsApp, distribuição automática e remarcações.

## Onde gerir

| Superfície | Rota |
|------------|------|
| **Calendário** (principal) | `/painel/agenda/calendario` — clique ou arrastar em slot vazio; editar/excluir em bloqueio âmbar |
| **Wizard Horários** | `/painel/agenda/?tab=horarios` — criar, editar, excluir; opção dia inteiro |
| **API JSON** | `POST/PATCH/DELETE /painel/agenda/api/blocked-time` |

## Motor externo (Agendamento IA)

Tenants com `scheduling_engine != zapaction_internal` **não** podem criar/editar/excluir bloqueios no painel. `blocks.py` devolve `motor_externo` (HTTP 403 nas APIs).

Bloqueios **não** são sincronizados para o Agenda externo nesta fase (V1). Use os bloqueios do sistema externo se aplicável.

Verificação: `scheduling_uses_internal_motor(cliente_id)` em `services/scheduling/engine.py`.

## Dia inteiro

Checkbox **Dia inteiro** + data → `resolve_day_block_bounds()`:

1. Horários do profissional nesse dia da semana
2. Se vazio → horários da clínica (`professional_id` null)
3. Se ainda vazio → `00:00`–`23:59:59` no fuso da clínica

## Comportamento esperado

- **Excluir** bloqueio → slots voltam disponíveis **imediatamente** (sem cache)
- **Criar** bloqueio sobre marcação existente → marcação mantém-se; só novos books são bloqueados
- Exemplo válido: cliente às 14:00 + bloqueio 15:00–16:00 no mesmo profissional

## Rollback

1. Painel: excluir bloqueios no calendário ou wizard Horários
2. SQL de emergência:

```sql
DELETE FROM scheduling_blocked_times WHERE cliente_id = '<UUID>';
```

## Verificação automatizada

```bash
python3 scripts/verify_scheduling_blocks.py
python3 scripts/verify_scheduling_blocks.py --cliente-id <UUID>
```

## Testes unitários

```bash
python -m unittest tests.test_scheduling_blocks -q
```

## Piloto sugerido

Tenant com motor interno (ex.: `clinica-teste`, `d1ddf96e-e667-48dc-9975-362a9c539fe2`):

1. Criar bloqueio por profissional no calendário
2. Confirmar que slots desaparecem na agenda pública
3. Criar bloqueio **Toda a clínica** e confirmar que todos os profissionais ficam indisponíveis
4. Excluir bloqueio e confirmar slots de volta
5. Criar bloqueio sobre horário já marcado — marcação deve permanecer

## Ficheiros principais

- `services/scheduling/blocks.py` — regras de domínio
- `services/scheduling/repository.py` — CRUD + `busy_intervals_utc`
- `services/scheduling/calendar.py` — eventos `type: block` no calendário
- `panel/routes/scheduling.py` — rotas painel e APIs
- `panel/templates/scheduling/calendario.html` — UI calendário
- `panel/templates/scheduling/wizard.html` — secção Horários
