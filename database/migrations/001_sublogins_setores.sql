-- Migração: Sublogins e Setores
-- Execute no Supabase (SQL Editor). Cria tabelas setores, usuarios_internos, usuarios_internos_setores
-- e adiciona colunas em painel_conversacao_setor e historico_mensagens.

-- 1) Tabela setores (áreas de atuação definidas pelo cliente)
CREATE TABLE IF NOT EXISTS setores (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cliente_id uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
  nome text NOT NULL,
  ativo boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_setores_cliente_id ON setores(cliente_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_setores_cliente_nome ON setores(cliente_id, lower(trim(nome)));

-- 2) Tabela usuarios_internos (sublogins / funcionários)
CREATE TABLE IF NOT EXISTS usuarios_internos (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cliente_id uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
  nome text NOT NULL,
  email_login text NOT NULL,
  senha text NOT NULL,
  ativo boolean NOT NULL DEFAULT true,
  is_admin_cliente boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_usuarios_internos_cliente_id ON usuarios_internos(cliente_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_internos_email_cliente ON usuarios_internos(cliente_id, lower(trim(email_login)));

-- 3) Tabela usuarios_internos_setores (acesso do funcionário a setores)
CREATE TABLE IF NOT EXISTS usuarios_internos_setores (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  usuario_interno_id uuid NOT NULL REFERENCES usuarios_internos(id) ON DELETE CASCADE,
  setor_id uuid NOT NULL REFERENCES setores(id) ON DELETE CASCADE,
  UNIQUE(usuario_interno_id, setor_id)
);

CREATE INDEX IF NOT EXISTS idx_ui_setores_usuario ON usuarios_internos_setores(usuario_interno_id);
CREATE INDEX IF NOT EXISTS idx_ui_setores_setor ON usuarios_internos_setores(setor_id);

-- 4) Colunas extras em painel_conversacao_setor (responsável humano + setor de negócio)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'painel_conversacao_setor' AND column_name = 'responsavel_usuario_id') THEN
    ALTER TABLE painel_conversacao_setor ADD COLUMN responsavel_usuario_id uuid REFERENCES usuarios_internos(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'painel_conversacao_setor' AND column_name = 'responsavel_nome_snapshot') THEN
    ALTER TABLE painel_conversacao_setor ADD COLUMN responsavel_nome_snapshot text;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'painel_conversacao_setor' AND column_name = 'setor_id') THEN
    ALTER TABLE painel_conversacao_setor ADD COLUMN setor_id uuid REFERENCES setores(id) ON DELETE SET NULL;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_conversacao_setor_responsavel ON painel_conversacao_setor(responsavel_usuario_id);

-- 5) Colunas extras em historico_mensagens (atendente por mensagem)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'historico_mensagens' AND column_name = 'atendente_tipo') THEN
    ALTER TABLE historico_mensagens ADD COLUMN atendente_tipo text;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'historico_mensagens' AND column_name = 'atendente_usuario_id') THEN
    ALTER TABLE historico_mensagens ADD COLUMN atendente_usuario_id uuid REFERENCES usuarios_internos(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'historico_mensagens' AND column_name = 'atendente_nome_snapshot') THEN
    ALTER TABLE historico_mensagens ADD COLUMN atendente_nome_snapshot text;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_historico_atendente_usuario ON historico_mensagens(atendente_usuario_id);
