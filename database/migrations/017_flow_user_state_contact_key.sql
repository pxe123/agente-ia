-- Migração: chave estável do estado do fluxo por contact_id
-- Permite upsert por (cliente_id, canal, contact_id) durante a transição.

CREATE UNIQUE INDEX IF NOT EXISTS idx_flow_user_state_unique_contact
  ON flow_user_state(cliente_id, canal, contact_id);

