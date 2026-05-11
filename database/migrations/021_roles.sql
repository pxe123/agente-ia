-- 021_roles.sql
-- Persistência de roles (Fase 2). Mudança opcional e compatível.

alter table if exists public.clientes
  add column if not exists role text;

alter table if exists public.usuarios_internos
  add column if not exists role text;

-- Normalização simples (opcional): valores esperados
-- super_admin | tenant_admin | tenant_user
-- Não aplicamos constraint rígida aqui para não quebrar dados legados.

