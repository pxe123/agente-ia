# Runbook — ZapAction ↔ Agendamento IA

## Catálogo (painel ↔ Agenda)

- **Fonte de verdade do catálogo:** painel ZapAction (`scheduling_*` no Supabase). Cada alteração (ou abertura da agenda, ~90 s) envia **tenant-snapshot** ao Agendamento IA.
- **O que fica igual nos dois:** clínica (slug, timezone), profissionais (mesmos UUIDs), serviços, horários, vínculos profissional↔serviço.
- **Marcações:** criadas no motor Agenda; espelham-se no painel via webhook (`appointment.*`) ou import na aba Agendamentos.
- **Botão no painel:** «Sincronizar catálogo agora» (força snapshot imediato).

## Ordem de provisionamento

1. **Supabase:** aplicar migrações `023` … `026` (inclui `external_agenda_appointment_id`).
2. **Agendamento IA:** deploy, `alembic upgrade head`, `.env` com `DATABASE_URL`, `AGENT_BEARER_TOKEN`, `SESSION_SECRET`, `ADMIN_SUPER_*`.
3. **ZapAction:** copiar [`.env.example`](../.env.example) → `.env`; preencher secção Agendamento IA.
4. **Alinhar tokens:** `AGENDAMENTO_IA_API_KEY` (ZapAction) = `AGENT_BEARER_TOKEN` (Agenda); `ZAPACTION_WEBHOOK_SECRET` igual nos dois.
5. **Agenda:** `ZAPACTION_APPOINTMENT_WEBHOOK_URL` = `https://{APP_ZAPACTION}/webhook/agendamento-ia/appointments`.
6. **Painel ZapAction:** `/painel/agenda` — clínica, slug, profissionais, serviços, horários → verificar flash “sincronizados”.
7. **Agenda admin:** `/admin/tenants/{cliente_id}` — validar slug, vínculos profissional↔serviço, horários.
8. **Smoke:** `python scripts/verify_agendamento_ia_env.py` e checklist em [`agendamento_ia_integracao_checklist.md`](agendamento_ia_integracao_checklist.md).

## URLs públicas (matriz)

| URL | Quem gera | Uso |
|-----|-----------|-----|
| `{AGENDA}/v1/book/{slug}/page?phone=&name=` | ZapAction (`build_public_book_page_url`) | **Canónico** — WhatsApp / nó `agendamento_ia` |
| `{AGENDA}/v1/link/page?t=…` | `POST /v1/link/generate` | Legado tokenizado |
| `{ZAPACTION}/agenda/{slug}` | ZapAction local | Só `USE_INTERNAL_SCHEDULING=1` ou dev sem Agenda |

## Motor WhatsApp

- ZapAction → `POST {AGENDA}/v1/agendamento` (não `/webhook/agendamento-ia/...` do ZapAction).
- `USE_INTERNAL_SCHEDULING=0` em produção com Agenda configurado.

## Cancelamento no painel

- **Local:** cancela só em Supabase.
- **Agenda:** `POST /v1/agendamento` com `operation: cancel` + `booking.appointment_id` (`services/agendamento_ia_cancel.py`); confirmação espelhada via webhook.

## Reconciliação (opcional)

- Job: `services/jobs/agendamento_ia_reconcile.py` — `GET /v1/integrations/zapaction/appointments/export`.

## Google Calendar

- **Login Google abre no ZapAction** (domínio do painel), não no Agendamento IA.
- **Painel:** `/painel/agenda` → aba **Profissionais** → **Conectar Google** → Google → volta ao painel.
- **ZapAction `.env`:** `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, opcional `GOOGLE_OAUTH_REDIRECT_URI` (default `{APP}/painel/agenda/google/callback`).
- **Google Cloud Console:** adicionar redirect URI do ZapAction (além do callback do Agenda, se existir).
- Após OAuth, ZapAction envia tokens ao Agenda: `POST /v1/integrations/zapaction/google/tokens` (Bearer).
- **Agenda `.env`:** `USE_GOOGLE=true` (motor usa os tokens); credenciais Google no Agenda continuam necessárias para freebusy/eventos no servidor.
- Status / desligar: `GET .../google/status`, `POST .../google/disconnect` (Bearer).
- OAuth scopes: `calendar.events` + `calendar.events.freebusy` — ver `agendamento-ia/docs/google_oauth_scopes.md`.
- Erro `oauth_codigo_expirado`: ver `agendamento-ia/docs/google_oauth_troubleshooting.md`.
- **Sair do modo teste Google:** [`google_oauth_production_checklist.md`](google_oauth_production_checklist.md), [`google_oauth_verification_package.md`](google_oauth_verification_package.md), `python scripts/verify_google_oauth_env.py`.
