-- Módulo de agenda (tenant = clientes.id). Executar no Supabase SQL Editor.
-- Horários de trabalho: day_of_week 0=segunda … 6=domingo (Python weekday).

create table if not exists public.scheduling_settings (
  cliente_id uuid primary key references public.clientes(id) on delete cascade,
  timezone text not null default 'America/Sao_Paulo',
  public_name text,
  public_slug text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists scheduling_settings_public_slug_key
  on public.scheduling_settings (lower(public_slug))
  where public_slug is not null and length(trim(public_slug)) > 0;

create table if not exists public.scheduling_professionals (
  id uuid primary key default gen_random_uuid(),
  cliente_id uuid not null references public.clientes(id) on delete cascade,
  name text not null,
  active boolean not null default true,
  sort_order int not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_scheduling_professionals_cliente
  on public.scheduling_professionals (cliente_id);

create table if not exists public.scheduling_services (
  id uuid primary key default gen_random_uuid(),
  cliente_id uuid not null references public.clientes(id) on delete cascade,
  name text not null,
  duration_minutes int not null default 30,
  price_cents int,
  professional_id uuid references public.scheduling_professionals(id) on delete set null,
  active boolean not null default true,
  sort_order int not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_scheduling_services_cliente
  on public.scheduling_services (cliente_id);

create table if not exists public.scheduling_working_hours (
  id uuid primary key default gen_random_uuid(),
  cliente_id uuid not null references public.clientes(id) on delete cascade,
  professional_id uuid references public.scheduling_professionals(id) on delete cascade,
  day_of_week smallint not null check (day_of_week >= 0 and day_of_week <= 6),
  start_time time not null,
  end_time time not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (start_time < end_time)
);

create index if not exists idx_scheduling_working_hours_cliente
  on public.scheduling_working_hours (cliente_id);

create index if not exists idx_scheduling_working_hours_professional
  on public.scheduling_working_hours (professional_id);

create table if not exists public.scheduling_blocked_times (
  id uuid primary key default gen_random_uuid(),
  cliente_id uuid not null references public.clientes(id) on delete cascade,
  professional_id uuid references public.scheduling_professionals(id) on delete cascade,
  starts_at timestamptz not null,
  ends_at timestamptz not null,
  reason text,
  created_at timestamptz not null default now(),
  check (starts_at < ends_at)
);

create index if not exists idx_scheduling_blocked_cliente_range
  on public.scheduling_blocked_times (cliente_id, starts_at, ends_at);

create table if not exists public.scheduling_appointments (
  id uuid primary key default gen_random_uuid(),
  cliente_id uuid not null references public.clientes(id) on delete cascade,
  service_id uuid not null references public.scheduling_services(id) on delete restrict,
  professional_id uuid references public.scheduling_professionals(id) on delete set null,
  starts_at timestamptz not null,
  ends_at timestamptz not null,
  status text not null default 'confirmed'
    check (status in ('pending','confirmed','cancelled','no_show')),
  remote_id text,
  contact_phone text,
  notes text,
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (starts_at < ends_at)
);

create index if not exists idx_scheduling_appointments_cliente_start
  on public.scheduling_appointments (cliente_id, starts_at);

create index if not exists idx_scheduling_appointments_professional_start
  on public.scheduling_appointments (professional_id, starts_at)
  where professional_id is not null;

create index if not exists idx_scheduling_appointments_status
  on public.scheduling_appointments (cliente_id, status);
