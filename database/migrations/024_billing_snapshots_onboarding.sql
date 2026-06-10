-- Adiciona coluna de onboarding nos snapshots diários
ALTER TABLE public.billing_snapshots_daily
  ADD COLUMN IF NOT EXISTS onboarding int not null default 0;

