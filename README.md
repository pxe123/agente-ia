# ZapAction (SaaS) — Setup e Produção

## Stack
- Backend: Flask + Flask-Login + Socket.IO
- Banco: Supabase
- Billing: Mercado Pago (assinatura recorrente via `preapproval`)
- Jobs: RQ + Redis (opcional, recomendado em produção)

## Variáveis de ambiente (mínimo)
Crie `.env` na raiz do projeto.

### Obrigatórias
- `SECRET_KEY` (32+ chars aleatórios)
- `SUPABASE_URL`
- `SUPABASE_KEY`

### Billing (Mercado Pago)
- `MERCADOPAGO_ACCESS_TOKEN`
- `MERCADOPAGO_WEBHOOK_SECRET` (Assinatura secreta dos webhooks)
- `MERCADOPAGO_BACK_URL` (URL do seu painel para retorno do checkout)
- (opcional) `BILLING_GRACE_DAYS` (default: 5)

### Hardening
- `PRODUCTION=1`
- `CORS_ORIGINS=https://seu-dominio.com` (lista separada por vírgula)
- `REQUIRE_WEBHOOK_SIGNATURES=1`

### Jobs/Worker
- `REDIS_URL=redis://...`

### Observabilidade
- `SENTRY_DSN=...`
- (opcional) `SENTRY_TRACES_SAMPLE_RATE=0.1`

## Banco (Supabase) — colunas/tabelas necessárias para billing

### Tabela `clientes` (novas colunas)
- `billing_plan_key` (text)
- `billing_status` (text)
- `billing_current_period_end` (timestamptz ou text/iso)
- `mp_customer_id` (text, opcional)
- `mp_preapproval_id` (text)

### Tabela `billing_events` (idempotência)
- `event_id` (text, **unique**)
- `request_id` (text)
- `resource_type` (text)
- `data_id` (text)
- `raw_body` (text)
- `received_at` (timestamptz)
- `processed_at` (timestamptz)
- `status` (text)

> Opcional: tabela `subscriptions` para histórico (ver `database/models.py`).

## Rodar local
```bash
pip install -r requirements.txt
python app.py
```

## Rodar worker (produção)
Com `REDIS_URL` configurado:
```bash
python worker.py
```

## Endpoints principais (billing)
- `POST /api/billing/mp/checkout` (cria assinatura/preapproval e retorna `init_point`)
- `GET /api/billing/status` (status atual salvo no `clientes`)
- `POST /webhook/mercadopago` (webhook Mercado Pago, com assinatura + idempotência)

