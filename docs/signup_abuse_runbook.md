# Runbook: abuso no cadastro público (`POST /cadastro`)

## Sintoma

Pico de linhas em `clientes` com `billing_status=onboarding`, e-mails aleatórios, sem uso do produto.

## Camadas na aplicação (ZapAction)

| Camada | Onde |
|--------|------|
| Kill switch | `PUBLIC_SIGNUP_DISABLED=1` → cadastro indisponível |
| Rate limit | `base/signup_security.py` — 3/h e 10/dia por IP |
| Turnstile | `TURNSTILE_SITE_KEY` + `TURNSTILE_SECRET_KEY` |
| Honeypot | campo oculto `website` no formulário |
| E-mail descartável | `services/signup_protection.py` |
| Logs | `signup_security event=signup_attempt|signup_blocked` |

## Cloudflare (recomendado em paralelo)

Configurar no painel do domínio público (ex.: zapaction.com.br):

1. **Rate limiting** — regra para `POST */cadastro`:
   - Limite sugerido: **5 pedidos / minuto / IP**
   - Ação: Block ou Managed Challenge

2. **WAF / Bot Fight** — na rota `GET` e `POST` `/cadastro`:
   - Managed Challenge ou JS Challenge na página de cadastro

3. **Opcional** — se o tráfego legítimo for só Brasil:
   - Regra geo: permitir apenas `BR` no path `/cadastro` (avaliar impacto em clientes no exterior)

4. **Headers** — garantir que o origin envia `X-Forwarded-For` corretamente para o rate limit da app.

## Limpeza pós-ataque

```bash
cd ~/agente-ia

# Listar candidatos (dry-run)
./venv/bin/python3 scripts/cleanup_signup_spam.py

# Aplicar após revisão manual da lista
./venv/bin/python3 scripts/cleanup_signup_spam.py --apply

# Janela customizada (ISO date)
./venv/bin/python3 scripts/cleanup_signup_spam.py --since 2026-05-20
```

Critérios do script: `billing_status=onboarding`, criados desde `--since` (default: hoje UTC). Se existir a coluna `activated_at` (migração `023_onboarding_funnel.sql`), exclui contas já ativadas.

Se `git pull` falhar no servidor (`not a git repository`), copie o script atualizado ou use `PYTHONPATH=/home/ubuntu/agente-ia` ao executar.

## Monitorização (24–48 h após deploy)

- Logs: picos de `signup_blocked` com `reason=rate_limit|turnstile|honeypot`
- Admin → Clientes: filtro «Ocultar onboarding» / «Criados hoje»
- Contagem de novos `onboarding` deve estabilizar

## Chaves Turnstile

1. [Cloudflare Dashboard](https://dash.cloudflare.com/) → Turnstile → Add site
2. Copiar Site Key e Secret Key para `.env`
3. Em produção, **ambas** as chaves são obrigatórias (cadastro bloqueado se ausentes)
