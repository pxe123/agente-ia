# Runbook: agendamentos recorrentes (painel)

## Pré-requisitos

- Migration `033_recurrence_series.sql` aplicada no Supabase.
- Migration `034_recurrence_motor_sync.sql` (índice retry sync motor).
- Recorrência disponível para **todos** os motores (`zapaction_internal` e `agendamento_ia`).

## Criação

1. Painel → Calendário ou Lista → **Novo agendamento** / clique em slot vazio.
2. Escolha **Recorrente**, frequência e regras.
3. Ocorrências são materializadas até **90 dias** à frente (`HORIZON_DAYS`).
4. Motor externo: ocorrências são enviadas ao Agendamento IA via integração HTTP.

## Motor externo (Agendamento IA)

- Contrato: `docs/agendamento_ia_recurrence_contract.md`
- Referência implementação Agenda IA: `docs/agendamento_ia_recurrence_agenda_ia_reference.py`
- Env `RECURRENCE_EXTERNAL_SYNC_ENABLED` (default `true`) — desativar para rollout gradual.
- Sync pendente: `meta.motor_sync=pending` — job `recurrence_expander` e reconcile retentam.

## Criação

1. Painel → Calendário → clique/arraste em slot vazio → **Agendamento**.
2. Escolha **Recorrente**, frequência e regras.
3. Ocorrências são materializadas até **90 dias** à frente (`HORIZON_DAYS`).

## Job de expansão

```bash
python -c "from services.jobs.recurrence_expander import run_recurrence_expander; print(run_recurrence_expander())"
```

O calendário também dispara expansão leve ao abrir (por tenant).

## Gestão da série

| Ação | Efeito |
|------|--------|
| Pausar | Cancela futuras; status `paused` |
| Reativar | Status `active` + reexpande |
| Encerrar | `ended` + cancela futuras |

## Cancelamento com escopo

No modal da ocorrência: `1` só esta, `2` esta e futuras, `3` toda a série.

Skips em `scheduling_recurrence_skips` evitam regenerar ocorrência cancelada isoladamente.

## Conflitos

Se slot ocupado (marcação ou bloqueio), a ocorrência é **omitida** e contada em `skipped_conflict`.

## WhatsApp

Opcional na criação: checkbox «Enviar resumo por WhatsApp». Uma mensagem por série (não por ocorrência).

## Compatibilidade

- Bloqueios, pool, confirmação: ocorrências são rows normais em `scheduling_appointments`.
- Criação painel: status `confirmed`, `meta.source = panel_recurrence`.
- Agenda pública / WhatsApp: sem criação de série.
