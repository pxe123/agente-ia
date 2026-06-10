-- Motor de agenda por tenant (substitui allowlist .env como fonte definitiva).
-- Valores: agendamento_ia | zapaction_internal

ALTER TABLE public.scheduling_settings
  ADD COLUMN IF NOT EXISTS scheduling_engine text NOT NULL DEFAULT 'agendamento_ia',
  ADD COLUMN IF NOT EXISTS scheduling_engine_changed_at timestamptz,
  ADD COLUMN IF NOT EXISTS scheduling_engine_changed_by text;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'scheduling_settings_scheduling_engine_check'
  ) THEN
    ALTER TABLE public.scheduling_settings
      ADD CONSTRAINT scheduling_settings_scheduling_engine_check
      CHECK (scheduling_engine IN ('agendamento_ia', 'zapaction_internal'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_scheduling_settings_scheduling_engine
  ON public.scheduling_settings (scheduling_engine);
