-- Chave de embed única por cliente (multi-tenant).
-- Formato: emb_ + base64url de 32 bytes (equivalente a secrets.token_urlsafe(32) no Python).
-- Copia de website_chat_embed_key quando existir; gera valor novo para quem não tinha.

-- 1) Coluna (nullable até backfill completo)
ALTER TABLE public.clientes
  ADD COLUMN IF NOT EXISTS embed_key text;

-- 2) Migrar valores da coluna legada (se existir neste projeto)
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'clientes' AND column_name = 'website_chat_embed_key'
  ) THEN
    UPDATE public.clientes c
    SET embed_key = NULLIF(trim(c.website_chat_embed_key), '')
    WHERE (c.embed_key IS NULL OR trim(c.embed_key) = '')
      AND c.website_chat_embed_key IS NOT NULL
      AND trim(c.website_chat_embed_key) != '';
  END IF;
END $$;

-- 3) Gerar chave para quem ainda não tem
UPDATE public.clientes c
SET embed_key = 'emb_' || rtrim(translate(encode(gen_random_bytes(32), 'base64'), '+/', '-_'), '=')
WHERE c.embed_key IS NULL OR trim(c.embed_key) = '';

-- 4) Eliminar duplicados (mantém o menor id por chave; regenera os demais)
WITH d AS (
  SELECT id,
         row_number() OVER (PARTITION BY embed_key ORDER BY id) AS rn
  FROM public.clientes
  WHERE embed_key IS NOT NULL AND trim(embed_key) <> ''
)
UPDATE public.clientes c
SET embed_key = 'emb_' || rtrim(translate(encode(gen_random_bytes(32), 'base64'), '+/', '-_'), '=')
FROM d
WHERE c.id = d.id AND d.rn > 1;

-- 5) Obrigatório e único
ALTER TABLE public.clientes
  ALTER COLUMN embed_key SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_clientes_embed_key ON public.clientes (embed_key);

-- 6) Novos inserts recebem chave automática se não informada
ALTER TABLE public.clientes
  ALTER COLUMN embed_key SET DEFAULT (
    'emb_' || rtrim(translate(encode(gen_random_bytes(32), 'base64'), '+/', '-_'), '=')
  );

-- 7) Manter coluna legada alinhada (ferramentas / rollback); ignorado se não existir
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'clientes' AND column_name = 'website_chat_embed_key'
  ) THEN
    UPDATE public.clientes
    SET website_chat_embed_key = embed_key
    WHERE website_chat_embed_key IS DISTINCT FROM embed_key;
  END IF;
END $$;
