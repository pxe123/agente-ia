-- WhatsApp (WAHA / canal whatsapp) no kill switch global, alinhado a Instagram/Messenger.
-- Execute no Supabase SQL Editor após 007_app_settings.sql.

ALTER TABLE app_settings
  ADD COLUMN IF NOT EXISTS whatsapp_enabled boolean NOT NULL DEFAULT true;
