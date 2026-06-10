-- Onboarding funnel (onboarding -> pending -> trialing -> active)
-- Campos para analytics/funil e transição de estados.

-- Aviso: execute via o mecanismo de migrations existente do projeto.

-- Versão do funil de signup:
-- 1 = legado (trial interno no cadastro)
-- 2 = onboarding funnel (trial após cartão/preapproval confirmado)
ALTER TABLE clientes
  ADD COLUMN IF NOT EXISTS signup_flow_version INTEGER NOT NULL DEFAULT 1;

-- Quando o usuário conclui a etapa de checkout (pagamento confirmado via webhook MP)
ALTER TABLE clientes
  ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMPTZ NULL;

-- Quando o produto passa a estar realmente ativo para o funil de trial (ex.: trial_started -> trialing)
ALTER TABLE clientes
  ADD COLUMN IF NOT EXISTS activated_at TIMESTAMPTZ NULL;

