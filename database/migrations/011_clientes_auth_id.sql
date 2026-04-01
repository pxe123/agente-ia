-- Vínculo explícito com Supabase Auth (auth.users.id). PK clientes.id permanece para FKs.
alter table if exists public.clientes
  add column if not exists auth_id uuid;

create unique index if not exists clientes_auth_id_key on public.clientes (auth_id) where auth_id is not null;

create index if not exists idx_clientes_auth_id on public.clientes (auth_id);

-- Não copiar id -> auth_id à cegas: só quando existe utilizador com esse id em auth.users.
-- Caso contrário auth_id fica NULL (vínculo criado depois via login ou POST /auth/update-access).
-- Evita inconsistência: clientes.auth_id só aponta para um UUID que realmente existe no Auth.
update public.clientes c
set auth_id = c.id
where c.auth_id is null
  and c.id is not null
  and exists (
    select 1
    from auth.users u
    where u.id = c.id
  );
