# ZapAction (SaaS) — Setup e Produção

## Stack
- Backend: Flask + Flask-Login + Socket.IO
- Banco: Supabase
- Billing: Stripe (Checkout + Customer Portal + Webhook)
- Jobs: RQ + Redis (opcional, recomendado em produção)

## Variáveis de ambiente (mínimo)
Crie `.env` na raiz do projeto.

### Obrigatórias
- `SECRET_KEY` (32+ chars aleatórios)
- `SUPABASE_URL`
- `SUPABASE_KEY` (service role — REST/admin no servidor)
- `SUPABASE_ANON_KEY` (anon public — **login** `/auth/login` e página `/nova-senha`)

Aliases aceitos: `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_PUBLISHABLE_KEY`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`.

Validar no servidor: `python scripts/verify_supabase_env.py` (após deploy/restart).

### Billing (Stripe)
- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_WEBHOOK_SECRET`
- Preços/planos: tabela **`plans`** no Supabase (`price`, `currency`, `trial_days`, `stripe_price_id`) — migration `029_plans_stripe_ids.sql`
- `STRIPE_SUCCESS_URL`, `STRIPE_CANCEL_URL`, `STRIPE_PORTAL_RETURN_URL`
- (opcional) `BILLING_GRACE_DAYS` (default: 5)

Endpoints Stripe:
- `POST /api/billing/stripe/create-checkout-session` → retorna `checkout_url`
- `POST /api/billing/stripe/customer-portal` → retorna `url` do portal
- `POST /api/billing/stripe/webhook` → webhook (Stripe-Signature)
- `GET /api/billing/status` → status atual salvo no `clientes`

**Assinantes Mercado Pago legados:** mantêm acesso read-only até `billing_current_period_end` (sem novos fluxos MP). Renovação/upgrade/cancelamento futuro: somente Stripe.

### Administradores da plataforma (painel `/admin`)
- `ADMIN_EMAIL` — e-mail principal (mestre).
- `ADMIN_EMAILS` — e-mails adicionais com o mesmo acesso administrativo (lista separada por vírgula; espaços em volta de cada e-mail são ignorados). Ex.: `ADMIN_EMAILS=outro@empresa.com, suporte@empresa.com`
- Todos precisam de utilizador no Supabase Auth com o mesmo e-mail para fazer login. A função `is_admin_like()` agrupa `ADMIN_EMAIL` e `ADMIN_EMAILS`.

### Hardening
- `PRODUCTION=1`
- `CORS_ORIGINS=https://seu-dominio.com` (lista separada por vírgula)
- `REQUIRE_WEBHOOK_SIGNATURES=1`

### Jobs/Worker
- `REDIS_URL=redis://...`

### Agendamento IA (agenda + nó `agendamento_ia`)
- Ver [`.env.example`](.env.example) e [`docs/agendamento_ia_runbook.md`](docs/agendamento_ia_runbook.md)
- `AGENDAMENTO_IA_BASE_URL`, `AGENDAMENTO_IA_API_KEY`, `ZAPACTION_WEBHOOK_SECRET`, `USE_INTERNAL_SCHEDULING=0` (prod)
- Migrações Supabase `023`–`026`; smoke: `python scripts/verify_agendamento_ia_env.py`

### Google Calendar (OAuth no painel)
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI` (ou `APP_BASE_URL` + `/painel/agenda/google/callback`)
- Smoke: `python scripts/verify_google_oauth_env.py`
- Sair do modo teste Google: [`docs/google_oauth_production_checklist.md`](docs/google_oauth_production_checklist.md), [`docs/google_oauth_verification_package.md`](docs/google_oauth_verification_package.md)

### Observabilidade
- `SENTRY_DSN=...`
- (opcional) `SENTRY_TRACES_SAMPLE_RATE=0.1`

## Banco (Supabase) — colunas/tabelas necessárias para billing

### Tabela `clientes` (novas colunas)
- `billing_plan_key` (text)
- `billing_status` (text)
- `billing_current_period_end` (timestamptz ou text/iso)
- `stripe_customer_id`, `stripe_subscription_id`, `stripe_price_id` (Stripe)
- `mp_preapproval_id`, `mp_customer_id` (legado MP — auditoria/graça)

### Tabela `billing_events` (idempotência)
- `event_id` (text, **unique**)
- `request_id` (text)
- `resource_type` (text) — `stripe` ou legado MP
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

## Migrações Supabase (Stripe)
- Aplicar `database/migrations/027_stripe_billing.sql`

## Deploy billing (produção)
1. Configurar `.env` Stripe (Price IDs + webhook `https://api.updigitalbrasil.com.br/api/billing/stripe/webhook`)
2. Aplicar migração SQL 027
3. Reiniciar Gunicorn/systemd
4. Desativar webhook Mercado Pago no painel MP (evita eventos órfãos)
