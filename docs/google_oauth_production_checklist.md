# Checklist — Google OAuth / Calendar em produção

Use este documento para auditar o projeto no Google Cloud Console e preparar a saída do modo **Testing**.

## 1. Auditoria rápida no servidor

```bash
# ZapAction
cd ~/agente-ia && source venv/bin/activate
python scripts/verify_google_oauth_env.py

# Agendamento IA (motor Calendar API)
cd ~/agendamento-ia && source .venv/bin/activate
python scripts/verify_google_calendar_env.py
curl -s http://127.0.0.1:8000/health/google
```

Anote o `oauth_callback_efetivo` — deve estar **idêntico** no OAuth client do Console.

## 2. Google Cloud Console — APIs

| Item | Onde | Esperado |
|------|------|----------|
| Google Calendar API | APIs & Services → Library | **Enabled** |
| OAuth consent screen | APIs & Services → OAuth consent screen | Preenchido |
| OAuth 2.0 Client | APIs & Services → Credentials | Web client com redirect URI |

## 3. OAuth consent screen (valores recomendados)

| Campo | Valor |
|-------|-------|
| User type | **External** |
| App name | **ZapAction** |
| User support email | contato@updigitalbrasil.com.br |
| App logo | Logo ZapAction (quadrado) |
| App home page | https://zapaction.com.br |
| Privacy policy | https://zapaction.com.br/politica |
| Terms of service | https://zapaction.com.br/termos |
| Authorized domains | zapaction.com.br, updigitalbrasil.com.br |
| Developer contact | e-mail(s) da equipa |

### Scopes declarados (Data Access)

Remover scopes antigos/largos. Manter apenas:

- `https://www.googleapis.com/auth/calendar.events`
- `https://www.googleapis.com/auth/calendar.events.freebusy`

**Não** declarar `https://www.googleapis.com/auth/calendar` (acesso total) se o código não o usa.

## 4. OAuth client — Redirect URIs

Registrar **exatamente** (sem barra final extra):

```
https://api.updigitalbrasil.com.br/painel/agenda/google/callback
```

Legado (só se ainda usar OAuth direto no Agenda):

```
https://agenda.zapaction.com.br/v1/google/oauth/callback
```

## 5. Search Console — verificação de domínios

1. Aceder a https://search.google.com/search-console com a **mesma conta Google** do projeto GCP
2. Adicionar propriedade **Prefixo de URL** `https://zapaction.com.br` (deve coincidir com *Application home page*)
3. Verificar via **DNS TXT** no registrador — o domínio já deve ter um registro `google-site-verification=...` em `zapaction.com.br`
4. Confirmar estado **Verificado** na propriedade antes de reverificar no Verification Center
5. No GCP → OAuth consent screen → **Authorized domains**: `zapaction.com.br` (e `updigitalbrasil.com.br` se usado)

### Reverificação da página inicial (após deploy da home)

1. GCP → **APIs & Services** → **OAuth consent screen** → **Verification Center**
2. Clicar em **Reverificar** nos requisitos da página inicial
3. Confirmar URLs exatas:
   - Home: `https://zapaction.com.br`
   - Privacy: `https://zapaction.com.br/politica`

### Auditoria automatizada da home

```bash
python scripts/verify_oauth_homepage.py
```

Checks: secção `#agendamento`, link `/politica`, disclosure de dados Google, política acessível sem login.

## 6. Publishing status

| Estado | Significado |
|--------|-------------|
| **Testing** | Máx. 100 test users; refresh token 7 dias; aviso “app não verificado” |
| **In production** (sem verificação) | Bloqueado para scopes sensíveis até aprovação |
| **In production** + **Verified** | Qualquer utilizador Google pode autorizar |

Fluxo: preencher consent screen → **Publish app** → **Submit for verification** (scopes sensíveis).

## 7. Pacote de submissão

Ver [`google_oauth_verification_package.md`](google_oauth_verification_package.md) — justificativas, roteiro de vídeo e passos de submissão.

## 8. Pós-aprovação

Ver [`google_oauth_post_approval.md`](google_oauth_post_approval.md).
