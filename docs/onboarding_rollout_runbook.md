# Runbook: onboarding/signup com trial pós-cartão (v2)

## Escopo
Este documento descreve um rollout seguro do funil novo com `billing_status`:
`onboarding -> pending -> trialing -> active`, ativado por feature flag.

Ele também contém contingências (SQL) para tenants que fiquem “presos” em `onboarding` ou `pending`.

## Pré-requisitos
- Migrações aplicadas:
  - `023_onboarding_funnel.sql` (campos em `clientes`)
  - `024_billing_snapshots_onboarding.sql` (coluna `onboarding` em `billing_snapshots_daily`)
- Deploy do código que implementa:
  - `USE_ONBOARDING_FUNNEL`
  - transição no webhook MP para `trialing`
  - guards que bloqueiam automações/WAHA/IA no período `onboarding/pending`

## Rollout (recomendado por etapas)
1. Deploy da versão com o funil (com `USE_ONBOARDING_FUNNEL` desligado).
2. Validar que o sistema opera para clientes legados:
   - login/integrações legadas
   - trial legado (`signup_flow_version=1`)
3. Ativar migrações (se ainda não estiverem aplicadas).
4. Ativar flag progressivamente:
   - `USE_ONBOARDING_FUNNEL=1`
5. Monitorar:
   - tenants com `signup_flow_version=2`
   - tempo em `billing_status='pending'` e `'onboarding'`
   - volume de eventos de billing (tabela `billing_events`)

## Como identificar tenants “presos”
Use como referência (PostgREST/Supabase SQL admin):

```sql
select
  id,
  email,
  plano,
  billing_plan_key,
  billing_status,
  signup_flow_version,
  mp_preapproval_id,
  created_at,
  onboarding_completed_at,
  activated_at,
  trial_ends_at
from public.clientes
where signup_flow_version = 2
  and billing_status in ('onboarding', 'pending')
order by created_at desc
limit 50;
```

Critérios comuns de “preso”:
- `billing_status='pending'` por tempo anormal após checkout
- `billing_status='onboarding'` sem que o usuário tenha concluído checkout
- `mp_preapproval_id` presente mas sem transição para `trialing`

## Rollback (seguro)
1. Desligar feature flag:
   - `USE_ONBOARDING_FUNNEL=0`
2. Não altere automaticamente clientes legados (`signup_flow_version=1`).
3. Para reduzir risco em tenants v2 presos, escolha uma das opções abaixo (contingência):
   - **Opção A (bloqueia para evitar acesso indevido)**: mover para `pending`/`inactive`
   - **Opção B (destrava acesso pago)**: mover para `active` (sem trial)

## Contingência SQL (opções)

### Opção A: bloquear (forçar novo checkout/fluxo)
Use quando houver dúvida se o pagamento foi confirmado/associado.

```sql
-- Move tenants v2 que ficaram em onboarding para pending/inactive
update public.clientes
set
  billing_status = 'pending',
  trial_ends_at = null,
  onboarding_completed_at = null,
  activated_at = null
where signup_flow_version = 2
  and billing_status = 'onboarding';

-- (Opcional) se você preferir um bloqueio mais forte:
-- update public.clientes
-- set billing_status='inactive'
-- where signup_flow_version=2 and billing_status='pending';
```

Observação: com guards, `pending`/`onboarding` continuam bloqueando automações/IA/WAHA.

### Opção B: destravar acesso (tolerante, baseado em “pagamento já ocorreu”)
Use quando você tem alta confiança de que houve confirmação no Mercado Pago (ex.: `mp_preapproval_id` existe e há consistência operacional).

```sql
-- Destrava tenants v2 para active (sem recomputar trial_ends_at)
update public.clientes
set
  billing_status = 'active',
  trial_ends_at = null,
  onboarding_completed_at = now(),
  activated_at = now()
where signup_flow_version = 2
  and billing_status in ('onboarding', 'pending');
```

Se a tabela `subscriptions` estiver acessível e você quiser alinhar “fonte de verdade” (best-effort):
```sql
update public.subscriptions s
set status = 'active',
    updated_at = now()
where s.cliente_id in (
  select id from public.clientes
  where signup_flow_version = 2
    and billing_status in ('onboarding', 'pending')
);
```

## Recomendações finais (segurança)
- Execute SQL **somente** para `signup_flow_version=2` para evitar regressões.
- Antes de optar por **Opção B**, valide presença de `mp_preapproval_id` e consistência de billing.
- Depois de qualquer contingência:
  - aguarde a rotina diária/refresh de snapshots (`billing_snapshots_daily`)
  - monitore se novas mensagens ainda disparam guards (sem custos indevidos)

