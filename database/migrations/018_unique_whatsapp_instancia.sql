-- Segurança multi-tenant: impede dois clientes de usarem a mesma sessão WAHA.
-- Execute no Supabase (SQL Editor) após verificar se não existem duplicatas atuais.

-- Diagnóstico opcional antes de aplicar:
-- SELECT whatsapp_instancia, COUNT(*)
-- FROM clientes
-- WHERE whatsapp_instancia IS NOT NULL AND btrim(whatsapp_instancia) <> ''
-- GROUP BY whatsapp_instancia
-- HAVING COUNT(*) > 1;

CREATE UNIQUE INDEX IF NOT EXISTS idx_clientes_whatsapp_instancia_unique
  ON clientes (whatsapp_instancia)
  WHERE whatsapp_instancia IS NOT NULL AND btrim(whatsapp_instancia) <> '';

COMMENT ON INDEX idx_clientes_whatsapp_instancia_unique IS
  'Garante que uma sessão WAHA (whatsapp_instancia) pertença a no máximo um cliente.';

