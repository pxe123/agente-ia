-- Login unificado: senha só no Supabase Auth; coluna legada opcional (como usuarios_internos).
alter table public.clientes
  alter column senha drop not null;
