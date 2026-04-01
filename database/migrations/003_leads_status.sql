-- Coluna status em leads: pendente | qualificado | desqualificado (para métricas de qualificação).
ALTER TABLE leads ADD COLUMN IF NOT EXISTS status text DEFAULT 'pendente';
