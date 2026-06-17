-- Modo de atribuição de profissional por tenant (manual | auto_distribution).

ALTER TABLE public.scheduling_settings
  ADD COLUMN IF NOT EXISTS professional_assignment_mode text NOT NULL DEFAULT 'manual',
  ADD COLUMN IF NOT EXISTS distribution_strategy text NOT NULL DEFAULT 'round_robin',
  ADD COLUMN IF NOT EXISTS distribution_last_professional_id uuid,
  ADD COLUMN IF NOT EXISTS assignment_mode_changed_at timestamptz,
  ADD COLUMN IF NOT EXISTS assignment_mode_changed_by text;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'scheduling_settings_professional_assignment_mode_check'
  ) THEN
    ALTER TABLE public.scheduling_settings
      ADD CONSTRAINT scheduling_settings_professional_assignment_mode_check
      CHECK (professional_assignment_mode IN ('manual', 'auto_distribution'));
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'scheduling_settings_distribution_strategy_check'
  ) THEN
    ALTER TABLE public.scheduling_settings
      ADD CONSTRAINT scheduling_settings_distribution_strategy_check
      CHECK (distribution_strategy IN ('round_robin', 'least_busy'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_scheduling_settings_assignment_mode
  ON public.scheduling_settings (professional_assignment_mode);
