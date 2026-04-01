-- Configuração global do SaaS (singleton id = 1).
-- Controle de canais Meta: mesmo com plano permitindo, o canal só funciona se estiver habilitado aqui.
-- Execute no Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS app_settings (
  id smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  instagram_enabled boolean NOT NULL DEFAULT true,
  messenger_enabled boolean NOT NULL DEFAULT true,
  whatsapp_enabled boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO app_settings (id, instagram_enabled, messenger_enabled, whatsapp_enabled)
VALUES (1, true, true, true)
ON CONFLICT (id) DO NOTHING;

COMMENT ON TABLE app_settings IS 'Singleton: flags globais (kill switch por canal, ex.: WhatsApp WAHA, Instagram, Messenger).';
