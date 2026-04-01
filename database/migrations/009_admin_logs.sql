-- Auditoria de ações no painel Admin (planos, canais globais, etc.)
-- Execute no Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS admin_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  admin_id text,
  action text NOT NULL,
  target_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_admin_logs_created_at ON admin_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_logs_action ON admin_logs (action);

COMMENT ON TABLE admin_logs IS 'Auditoria: edições de plano, flags globais de canal, etc.';
