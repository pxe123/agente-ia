-- Vínculo de funcionários (usuarios_internos) com Supabase Auth (auth.users.id).
-- Senha passa a ser só no Auth; coluna senha fica opcional (legado até migração completa).

alter table if exists public.usuarios_internos
  add column if not exists auth_id uuid;

create unique index if not exists usuarios_internos_auth_id_key
  on public.usuarios_internos (auth_id) where auth_id is not null;

create index if not exists idx_usuarios_internos_auth_id on public.usuarios_internos (auth_id);

-- Permitir linhas só com Auth (sem hash local).
alter table public.usuarios_internos alter column senha drop not null;
