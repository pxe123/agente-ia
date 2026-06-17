-- Política de confirmação de agendamento por tenant (auto | professional | reception).
-- Propostas de remarcação e tokens de link seguro.

ALTER TABLE public.scheduling_settings
  ADD COLUMN IF NOT EXISTS confirmation_policy text NOT NULL DEFAULT 'auto',
  ADD COLUMN IF NOT EXISTS confirmation_pending_ttl_hours int NOT NULL DEFAULT 48,
  ADD COLUMN IF NOT EXISTS confirmation_policy_changed_at timestamptz,
  ADD COLUMN IF NOT EXISTS confirmation_policy_changed_by text;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'scheduling_settings_confirmation_policy_check'
  ) THEN
    ALTER TABLE public.scheduling_settings
      ADD CONSTRAINT scheduling_settings_confirmation_policy_check
      CHECK (confirmation_policy IN ('auto', 'professional', 'reception'));
  END IF;
END $$;

ALTER TABLE public.scheduling_professionals
  ADD COLUMN IF NOT EXISTS whatsapp_notify_phone text;

CREATE TABLE IF NOT EXISTS public.scheduling_appointment_proposals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  appointment_id uuid NOT NULL REFERENCES public.scheduling_appointments(id) ON DELETE CASCADE,
  cliente_id uuid NOT NULL REFERENCES public.clientes(id) ON DELETE CASCADE,
  proposed_starts_at timestamptz NOT NULL,
  proposed_ends_at timestamptz NOT NULL,
  proposed_by text NOT NULL,
  status text NOT NULL DEFAULT 'open',
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT scheduling_appointment_proposals_status_check
    CHECK (status IN ('open', 'accepted', 'declined', 'superseded'))
);

CREATE INDEX IF NOT EXISTS idx_scheduling_appointment_proposals_appointment
  ON public.scheduling_appointment_proposals (appointment_id, status);

CREATE TABLE IF NOT EXISTS public.scheduling_confirmation_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  token_hash text NOT NULL UNIQUE,
  appointment_id uuid NOT NULL REFERENCES public.scheduling_appointments(id) ON DELETE CASCADE,
  proposal_id uuid REFERENCES public.scheduling_appointment_proposals(id) ON DELETE CASCADE,
  cliente_id uuid NOT NULL REFERENCES public.clientes(id) ON DELETE CASCADE,
  action text NOT NULL,
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT scheduling_confirmation_tokens_action_check
    CHECK (action IN ('accept_proposal', 'decline_proposal', 'human_handoff'))
);

CREATE INDEX IF NOT EXISTS idx_scheduling_confirmation_tokens_appointment
  ON public.scheduling_confirmation_tokens (appointment_id);
