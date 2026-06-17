-- Séries recorrentes (painel admin) + ocorrências materializadas em scheduling_appointments.

create table if not exists public.scheduling_recurrence_series (
  id uuid primary key default gen_random_uuid(),
  cliente_id uuid not null references public.clientes(id) on delete cascade,
  service_id uuid not null references public.scheduling_services(id) on delete restrict,
  professional_id uuid references public.scheduling_professionals(id) on delete set null,
  status text not null default 'active'
    check (status in ('active', 'paused', 'ended')),
  frequency text not null
    check (frequency in ('daily', 'weekly', 'monthly')),
  rule jsonb not null default '{}'::jsonb,
  time_local time not null,
  starts_on date not null,
  ends_on date,
  contact_name text not null default '',
  contact_phone text,
  notes text,
  meta jsonb not null default '{}'::jsonb,
  materialized_until date,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (ends_on is null or ends_on >= starts_on)
);

create index if not exists idx_scheduling_recurrence_series_cliente
  on public.scheduling_recurrence_series (cliente_id);

create index if not exists idx_scheduling_recurrence_series_status
  on public.scheduling_recurrence_series (cliente_id, status);

create table if not exists public.scheduling_recurrence_skips (
  id uuid primary key default gen_random_uuid(),
  cliente_id uuid not null references public.clientes(id) on delete cascade,
  series_id uuid not null references public.scheduling_recurrence_series(id) on delete cascade,
  occurrence_date date not null,
  created_at timestamptz not null default now(),
  unique (series_id, occurrence_date)
);

create index if not exists idx_scheduling_recurrence_skips_series
  on public.scheduling_recurrence_skips (series_id, occurrence_date);

alter table public.scheduling_appointments
  add column if not exists recurrence_series_id uuid
    references public.scheduling_recurrence_series(id) on delete set null;

alter table public.scheduling_appointments
  add column if not exists series_occurrence_at timestamptz;

alter table public.scheduling_appointments
  add column if not exists is_series_exception boolean not null default false;

create unique index if not exists scheduling_appointments_series_occurrence_key
  on public.scheduling_appointments (recurrence_series_id, series_occurrence_at)
  where recurrence_series_id is not null and series_occurrence_at is not null;

create index if not exists idx_scheduling_appointments_recurrence_series
  on public.scheduling_appointments (cliente_id, recurrence_series_id, starts_at)
  where recurrence_series_id is not null;

create index if not exists idx_scheduling_appointments_series_status
  on public.scheduling_appointments (recurrence_series_id, status)
  where recurrence_series_id is not null;
