-- Egress por tenant (proxy por sessão WAHA)
-- Objetivo: isolar tráfego por cliente via proxy configurado na criação da sessão WAHA.
-- Execute no Supabase (SQL Editor).

-- 1) Perfis de egress (proxies)
CREATE TABLE IF NOT EXISTS egress_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL UNIQUE,
  host text NOT NULL,
  port int NOT NULL,
  username text NULL,
  password text NULL,
  type text NULL, -- metadata: http|socks5 (não enviado ao WAHA)
  country text NULL,
  is_active boolean NOT NULL DEFAULT true,
  max_clients int NOT NULL DEFAULT 2,
  last_test_ip text NULL,
  last_test_latency int NULL, -- ms
  last_test_at timestamptz NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_egress_profiles_active ON egress_profiles (is_active);

-- 2) Assignments (1 tenant -> 1 profile)
CREATE TABLE IF NOT EXISTS egress_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  egress_profile_id uuid NOT NULL REFERENCES egress_profiles(id) ON DELETE RESTRICT,
  cliente_id uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (cliente_id)
);

CREATE INDEX IF NOT EXISTS idx_egress_assignments_profile ON egress_assignments (egress_profile_id);

-- 3) Controle de concorrência / capacidade via RPC
-- Usa lock na linha do profile para evitar corrida em max_clients.
CREATE OR REPLACE FUNCTION assign_egress_profile(p_cliente_id uuid, p_profile_id uuid)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  v_max int;
  v_active boolean;
  v_count int;
BEGIN
  -- Lock do profile
  SELECT max_clients, is_active
    INTO v_max, v_active
    FROM egress_profiles
   WHERE id = p_profile_id
   FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Egress profile não encontrado';
  END IF;

  IF v_active IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'Egress profile inativo';
  END IF;

  SELECT COUNT(*) INTO v_count
    FROM egress_assignments
   WHERE egress_profile_id = p_profile_id;

  IF v_count >= v_max THEN
    RAISE EXCEPTION 'Egress profile sem capacidade (max_clients=%)', v_max;
  END IF;

  INSERT INTO egress_assignments (egress_profile_id, cliente_id)
  VALUES (p_profile_id, p_cliente_id)
  ON CONFLICT (cliente_id)
  DO UPDATE SET egress_profile_id = EXCLUDED.egress_profile_id;
END;
$$;

COMMENT ON TABLE egress_profiles IS 'Perfis de egress (proxy) por tenant; aplicados em sessões WAHA.';
COMMENT ON TABLE egress_assignments IS 'Vínculo 1:1 (tenant->profile) para egress/proxy em sessões WAHA.';

