# Checklist — integração ZapAction ↔ Agendamento IA



## Variáveis ZapAction (`.env`)



Ver também [`.env.example`](../.env.example) e [`agendamento_ia_runbook.md`](agendamento_ia_runbook.md).



| Variável | Exemplo | Obrigatório em prod |

|----------|---------|---------------------|

| `AGENDAMENTO_IA_BASE_URL` | `https://agenda.zapaction.com.br` | Sim |

| `AGENDAMENTO_IA_API_KEY` | (= `AGENT_BEARER_TOKEN` do Agenda) | Sim |

| `ZAPACTION_WEBHOOK_SECRET` | igual no Agenda | Sim |

| `USE_INTERNAL_SCHEDULING` | `0` | Sim |



Opcionais (sobrescrevem derivados da BASE): `AGENDAMENTO_IA_WEBHOOK_URL`, `AGENDAMENTO_IA_CLINIC_SYNC_URL`, `AGENDAMENTO_IA_LINK_GENERATE_URL`, `AGENDAMENTO_IA_PUBLIC_BASE_URL`.



**Verificação rápida:** `python scripts/verify_agendamento_ia_env.py`



## Variáveis Agendamento IA



| Variável | Obrigatório |

|----------|-------------|

| `DATABASE_URL` | Sim |

| `AGENT_BEARER_TOKEN` | Sim |

| `SESSION_SECRET`, `ADMIN_SUPER_*` | Admin HTML |

| `LINK_TOKEN_SECRET` | Se usar `/v1/link/*` |

| `ZAPACTION_APPOINTMENT_WEBHOOK_URL` | `https://{APP_BASE}/webhook/agendamento-ia/appointments` |

| `ZAPACTION_WEBHOOK_SECRET` | Igual ao ZapAction |

| `PUBLIC_BASE_URL` | Links absolutos |



## Migrações Supabase (ZapAction)



Aplicar em ordem: `023_onboarding_funnel.sql` … `026_scheduling_appointments_external_agenda.sql`.



## E2E staging



1. `GET {BASE}/health` → `{"status":"ok"}`

2. Painel → guardar clínica/profissionais/serviços/horários → snapshot 2xx (flash “sincronizados”)

3. Fluxo WhatsApp com nó `agendamento_ia` → `POST /v1/agendamento` completa booking

4. Modo “só link” → cliente recebe URL `.../v1/book/{slug}/page?phone=...` (ou link tokenizado legado)

5. Webhook `appointment.created` → linha no painel com origem **Agenda**



## Sintomas comuns



| Sintoma | Verificação |

|---------|-------------|

| Link 503 `link_not_configured` | `LINK_TOKEN_SECRET` no Agenda |

| 401 ao gerar link | `AGENDAMENTO_IA_API_KEY` = `AGENT_BEARER_TOKEN` |

| Sem dias verdes no link | Snapshot + horários + `provider_services` no Agenda |

| WhatsApp não agenda | `USE_INTERNAL_SCHEDULING=0`, BASE configurada |

| Painel sem marcações | Webhook + secret; logs `/webhook/agendamento-ia/appointments` |

| Sync `http_500` / `tenant_snapshot_failed` | Ver `detail.reason` na resposta; deploy `agendamento-ia` com `zapaction_tenant_sync` atualizado (serviços + `provider_services` + prune) |
| Sync parcial «só clínica» | Agenda antigo no servidor — rebuild/deploy da imagem `agendamento-ia:latest` |

| `AGENDAMENTO_IA_WEBHOOK_URL` errado | Deve ser `.../v1/agendamento`, não `/webhook/agendamento-ia/...` do ZapAction |

| URL antiga `/agenda/slug` em prod | Configure `AGENDAMENTO_IA_BASE_URL`; links passam a `/v1/book/...` |

