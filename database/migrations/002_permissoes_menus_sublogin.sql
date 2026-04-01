-- Migração: Permissões de menu por sublogin
-- Execute no Supabase (SQL Editor). Adiciona coluna acesso_menus em usuarios_internos.
-- Chaves: chat, conexoes, chatbots, usuarios_setores. Default [] = só Dashboard e Perfil.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'usuarios_internos' AND column_name = 'acesso_menus'
  ) THEN
    ALTER TABLE usuarios_internos ADD COLUMN acesso_menus jsonb NOT NULL DEFAULT '[]';
  END IF;
END $$;
