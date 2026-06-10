-- Reduz custo de listagem/polling em historico_mensagens (cliente_id + canal + recência).
CREATE INDEX IF NOT EXISTS idx_historico_cliente_canal_created
  ON public.historico_mensagens (cliente_id, canal, created_at DESC);
