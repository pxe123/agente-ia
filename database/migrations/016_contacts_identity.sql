-- Migração: camada de identidade estável (contacts/contact_channels)
-- Objetivo: desacoplar identidade de remote_id (instável no WhatsApp) usando contact_id.
-- Execute no Supabase (SQL Editor).

-- 1) Tabela contacts (identidade principal por cliente; phone_normalized quando confiável)
CREATE TABLE IF NOT EXISTS contacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cliente_id uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
  phone_normalized text NULL,
  nome text NULL,
  email text NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_contacts_cliente_id ON contacts(cliente_id);
CREATE INDEX IF NOT EXISTS idx_contacts_phone_norm ON contacts(phone_normalized);
-- Um contato por telefone por cliente (quando phone_normalized existir).
CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_unique_cliente_phone
  ON contacts(cliente_id, phone_normalized)
  WHERE phone_normalized IS NOT NULL;

-- 2) Tabela contact_channels (mapeia remote_id(s) do provedor para um contact)
CREATE TABLE IF NOT EXISTS contact_channels (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cliente_id uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
  contact_id uuid NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  canal text NOT NULL,
  remote_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(cliente_id, canal, remote_id)
);

CREATE INDEX IF NOT EXISTS idx_contact_channels_contact ON contact_channels(contact_id);
CREATE INDEX IF NOT EXISTS idx_contact_channels_cliente_canal ON contact_channels(cliente_id, canal);

-- 3) leads: adicionar contact_id (nullable inicialmente; remote_id permanece para histórico)
ALTER TABLE leads
  ADD COLUMN IF NOT EXISTS contact_id uuid REFERENCES contacts(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_leads_contact_id ON leads(contact_id);

-- 4) flow_user_state: adicionar contact_id (nullable inicialmente; remote_id mantém compatibilidade)
ALTER TABLE flow_user_state
  ADD COLUMN IF NOT EXISTS contact_id uuid REFERENCES contacts(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_flow_user_state_contact_id ON flow_user_state(contact_id);

