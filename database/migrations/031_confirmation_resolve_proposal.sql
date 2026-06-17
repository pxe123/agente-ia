-- Token único para aceitar/recusar proposta na mesma página pública.

ALTER TABLE public.scheduling_confirmation_tokens
  DROP CONSTRAINT IF EXISTS scheduling_confirmation_tokens_action_check;

ALTER TABLE public.scheduling_confirmation_tokens
  ADD CONSTRAINT scheduling_confirmation_tokens_action_check
  CHECK (action IN ('accept_proposal', 'decline_proposal', 'human_handoff', 'resolve_proposal'));
