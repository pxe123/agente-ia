-- Configuração de rotinas de horário (UI) + personalização por dia
ALTER TABLE public.scheduling_settings
  ADD COLUMN IF NOT EXISTS working_hour_config jsonb NOT NULL DEFAULT '{}'::jsonb;
