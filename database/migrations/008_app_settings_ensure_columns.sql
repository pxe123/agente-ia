-- Garante colunas e linha singleton em app_settings (bases criadas antes de 007 ou alteradas manualmente).
-- Execute no Supabase SQL Editor se necessário.

CREATE TABLE IF NOT EXISTS app_settings (
  id smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  instagram_enabled boolean NOT NULL DEFAULT true,
  messenger_enabled boolean NOT NULL DEFAULT true,
  whatsapp_enabled boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE app_settings
  ADD COLUMN IF NOT EXISTS instagram_enabled boolean NOT NULL DEFAULT true;
ALTER TABLE app_settings
  ADD COLUMN IF NOT EXISTS messenger_enabled boolean NOT NULL DEFAULT true;
ALTER TABLE app_settings
  ADD COLUMN IF NOT EXISTS whatsapp_enabled boolean NOT NULL DEFAULT true;

INSERT INTO app_settings (id, instagram_enabled, messenger_enabled, whatsapp_enabled)
VALUES (1, true, true, true)
ON CONFLICT (id) DO NOTHING;
