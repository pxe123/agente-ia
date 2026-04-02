-- Backfill: preencher auth_id em contas antigas, alinhando e-mail com auth.users.
-- Executar no Supabase SQL Editor (ou psql) com permissão de leitura em auth.users.
--
-- Antes de correr o UPDATE, podes pré-visualizar:
--
-- SELECT c.id, c.email, c.auth_id, u.id AS auth_user_id
-- FROM public.clientes c
-- INNER JOIN auth.users u ON lower(trim(c.email)) = lower(trim(u.email::text))
-- WHERE c.auth_id IS NULL AND c.email IS NOT NULL AND btrim(c.email) <> '';
--
-- SELECT ui.id, ui.email_login, ui.auth_id, u.id AS auth_user_id
-- FROM public.usuarios_internos ui
-- INNER JOIN auth.users u ON lower(trim(ui.email_login)) = lower(trim(u.email::text))
-- WHERE ui.auth_id IS NULL AND ui.email_login IS NOT NULL AND btrim(ui.email_login) <> '';

-- Schema mínimo (idempotente). Se já aplicaste 011/012, estes comandos não alteram nada.
ALTER TABLE IF EXISTS public.clientes
  ADD COLUMN IF NOT EXISTS auth_id uuid;

CREATE UNIQUE INDEX IF NOT EXISTS clientes_auth_id_key ON public.clientes (auth_id) WHERE auth_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_clientes_auth_id ON public.clientes (auth_id);

ALTER TABLE IF EXISTS public.usuarios_internos
  ADD COLUMN IF NOT EXISTS auth_id uuid;

CREATE UNIQUE INDEX IF NOT EXISTS usuarios_internos_auth_id_key ON public.usuarios_internos (auth_id) WHERE auth_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_usuarios_internos_auth_id ON public.usuarios_internos (auth_id);

-- ---------------------------------------------------------------------------
-- 1) Donos: public.clientes.auth_id <- auth.users.id (match por e-mail)
--    Ignora UUID de auth já usado por outra linha de clientes.
--    Se houver dois clientes com o mesmo e-mail, só o de menor id recebe o vínculo.
-- ---------------------------------------------------------------------------
UPDATE public.clientes c
SET auth_id = sub.user_id
FROM (
    SELECT DISTINCT ON (lower(trim(c_inner.email)))
        c_inner.id AS cliente_id,
        u.id AS user_id
    FROM public.clientes c_inner
    INNER JOIN auth.users u
        ON lower(trim(c_inner.email)) = lower(trim(u.email::text))
    WHERE c_inner.auth_id IS NULL
      AND c_inner.email IS NOT NULL
      AND btrim(c_inner.email) <> ''
      AND NOT EXISTS (
          SELECT 1
          FROM public.clientes c2
          WHERE c2.auth_id = u.id
      )
    ORDER BY lower(trim(c_inner.email)), c_inner.id
) AS sub
WHERE c.id = sub.cliente_id;

-- ---------------------------------------------------------------------------
-- 2) Funcionários: public.usuarios_internos.auth_id (match por email_login)
--    Mesma lógica de conflito com outra linha que já use esse auth_id.
-- ---------------------------------------------------------------------------
UPDATE public.usuarios_internos ui
SET auth_id = sub.user_id
FROM (
    SELECT DISTINCT ON (lower(trim(ui_inner.email_login)))
        ui_inner.id AS operador_id,
        u.id AS user_id
    FROM public.usuarios_internos ui_inner
    INNER JOIN auth.users u
        ON lower(trim(ui_inner.email_login)) = lower(trim(u.email::text))
    WHERE ui_inner.auth_id IS NULL
      AND ui_inner.email_login IS NOT NULL
      AND btrim(ui_inner.email_login) <> ''
      AND NOT EXISTS (
          SELECT 1
          FROM public.usuarios_internos x
          WHERE x.auth_id = u.id
      )
    ORDER BY lower(trim(ui_inner.email_login)), ui_inner.id
) AS sub
WHERE ui.id = sub.operador_id;
