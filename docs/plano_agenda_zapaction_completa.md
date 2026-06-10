# Plano: agenda completa visível e fiável no ZapAction

**Decisão de arquitetura (atualizada):** integração **só por HTTP** — `tenant-snapshot` (config), motor `/v1/agendamento`, e **webhooks / eventos** (ex.: reverso para agendamentos). **Ligação direta ao mesmo banco de dados entre ZapAction e Agendamento IA está fora de escopo e descartada** (dois modelos, duas stacks; partilhar eventos, não BD mutável comum).

**Plano técnico executável + prompt para o Cursor:** [`plano_tecnico_continuacao_zapaction_agenda.md`](plano_tecnico_continuacao_zapaction_agenda.md) (fases, contratos, segurança, ficheiros e texto pronto a colar noutra conversa).

Objetivo: o utilizador no **painel ZapAction** vê e gere **toda a informação relevante da agenda** (clínica, equipa, serviços, horários e **agendamentos**), alinhada com o **Agendamento IA** quando esse motor está em uso — sem depender de “abrir outro sistema” para dados críticos.

## O que fazer com os “dois planos” (não são rivais)

| Ficheiro | Função | Quem lê / quando |
|----------|--------|------------------|
| **`plano_agenda_zapaction_completa.md`** (este) | **Produto + âmbito + fases A–D** em linguagem de roadmap (“o quê” e “porquê”) | Decisão de produto, prioridades, critérios de aceite |
| **`plano_tecnico_continuacao_zapaction_agenda.md`** | **Execução**: contratos JSON, HMAC, idempotência, pastas de código, prompt para o Cursor (“como”) | Desenvolvimento, implementação, PRs |

**Na prática:** é **um** roadmap em duas camadas — **complementares**, não duas estratégias. O “oficial” para **código** é o **plano técnico**; este ficheiro mantém a **visão** e o **gargalo** explícito (painel a mostrar agendamentos do Agenda).

**O que fazer *agora* (ordem):** seguir a **secção 9** do plano técnico (“Próximos passos imediatos”) — contrato JSON v1 do webhook estável (`event_id`, `occurred_at`) → receptor no ZapAction → emissor no Agenda → **teste fim-a-fim** em ambiente com migração Supabase aplicada e variáveis preenchidas.

---

## 1. Estado atual (baseline)

| Área | ZapAction (Supabase `scheduling_*`) | Agendamento IA (Postgres próprio) |
|------|-------------------------------------|-----------------------------------|
| Clínica / fuso / slug | Painel wizard + gravação local | Recebe `tenant-snapshot` (push ZA → Agenda) |
| Profissionais / serviços / horários | Painel + gravação local | Atualizado pelo snapshot |
| Agendamentos (quem marcou) | Lista marcações do motor interno ZA; **com Fase A ativa**, marcações criadas/canceladas no Agenda **podem** espelhar-se via webhook (requer migração `026` + env) | Motor `/v1/agendamento`; emissor webhook pós-commit (criar, cancelar; remarcação a fechar no Agenda) |
| Conversa WhatsApp | Nó `agendamento_ia` → webhook ou motor interno | Motor `/v1/agendamento` |

Ficheiros-chave ZapAction: [`panel/routes/scheduling.py`](../panel/routes/scheduling.py), [`panel/templates/scheduling/wizard.html`](../panel/templates/scheduling/wizard.html), [`services/agendamento_ia_sync.py`](../services/agendamento_ia_sync.py), [`services/scheduling/`](../services/scheduling/), webhook reverso [`webhooks/agendamento_ia_appointments.py`](../webhooks/agendamento_ia_appointments.py), [`services/agendamento_ia_appointment_webhook.py`](../services/agendamento_ia_appointment_webhook.py), migração [`database/migrations/026_scheduling_appointments_external_agenda.sql`](../database/migrations/026_scheduling_appointments_external_agenda.sql).

Ficheiros-chave Agenda: `POST /v1/integrations/zapaction/tenant-snapshot`, modelos em `app/db/models.py`, escrita de `AppointmentRow` no fluxo de booking, emissor em `app/services/zapaction_outbound.py` (repositório **agendamento-ia**).

**Lacuna que fechámos na Fase A (código):** canal **Agenda → ZapAction** para eventos `appointment.*` com HMAC e upsert idempotente (`cliente_id` + `appointment_id` do Agenda, coluna `external_agenda_appointment_id`).

**Ainda em aberto (produto/UX):** coluna **“Origem”** / “Última sync” no painel (Fase C), validação opcional de `cliente_id` contra tenant conhecido no receptor, remarcação explícita no emissor, reconciliação (Fase B), documentação runbook/README.

---

## 2. Definição de “todos os serviços da agenda” (âmbito)

Incluir no mínimo:

1. **Configuração** — já coberta pelo snapshot (com melhorias opcionais abaixo).
2. **Catálogo** — profissionais, serviços, horários (já no wizard; espelho no Agenda via snapshot).
3. **Agendamentos** — lista no passo “Agendamentos” com contacto, horário, estado, origem — **incluindo** os criados no motor Agenda (via webhook reverso ou pull).
4. **(Opcional)** Bloqueios, ligações Google, lembretes — só se forem requisito de produto; hoje são domínio maioritário do Agenda.

Se o produto quiser **só catálogo + marcações**, as fases 3–4 do roadmap de produto bastam; Google/blocks ficam fora ou fase posterior.

---

## 3. Fases de entrega

### Fase A — Contrato de eventos e webhook reverso (prioridade máxima)

**Agendamento IA**

- Após persistir alteração relevante em `appointments` (**criar**, **cancelar**; **remarcar** ainda por alinhar em todos os fluxos), **POST** assíncrono com retries leves para URL configurável.
- **Variáveis de ambiente (implementado):** `ZAPACTION_APPOINTMENT_WEBHOOK_URL` (URL completa, ex. `https://…/webhook/agendamento-ia/appointments`) e `ZAPACTION_WEBHOOK_SECRET` (partilhado com o ZapAction).
- Payload mínimo versionado, ex.:

```json
{
  "event": "appointment.created",
  "request_schema_version": 1,
  "event_id": "<uuid>",
  "occurred_at": "2026-05-14T12:00:00Z",
  "cliente_id": "<uuid>",
  "appointment_id": "<uuid Agenda>",
  "status": "confirmed",
  "starts_at": "<iso>",
  "ends_at": "<iso>",
  "provider_id": "...",
  "service_id": "...",
  "remote_id": "...",
  "contact": { "phone": "...", "name": "..." },
  "metadata": {}
}
```

Contrato canónico (campos, cabeçalhos, retries, idempotência): ver o plano técnico, blocos sobre **contratos JSON** e **idempotência**.

- Eventos suportados no receptor ZapAction: `appointment.created`, `appointment.cancelled`, `appointment.rescheduled`, `appointment.updated`. Repetir o mesmo par negócio não deve duplicar linhas (upsert por `external_agenda_appointment_id`).
- **Assinatura:** `X-Zapaction-Timestamp` + `X-Zapaction-Signature: sha256=…` com HMAC de `timestamp + "." + corpo_raw` (anti-replay, janela curta).

**ZapAction**

- Rota implementada: **`POST /webhook/agendamento-ia/appointments`** (prefixo `/webhook` alinhado a Meta, WAHA, Mercado Pago; pedido **fora** de CSRF de formulário no `app.py`).
- Validar HMAC; **validação explícita de `cliente_id` contra lista de tenants** é recomendada em endurecimento (pendente).
- **Upsert** em `scheduling_appointments`: coluna `external_agenda_appointment_id` (migração `026`) + `meta.agenda_webhook` para auditoria.
- Resposta 200 rápida; erros com código HTTP adequado; retries no lado Agenda.

**Critério de aceite:** marcação feita via conversa no motor Agenda aparece no painel ZapAction em **Agendamentos** em segundos (ou após retry), com Supabase migrado e segredos configurados.

---

### Fase B — Reconciliação e deriva (opcional mas útil)

- Job agendado (ex. diário) no ZapAction: `GET` export no Agenda (novo endpoint read-only) **ou** replay de últimos N eventos — para corrigir falhas de webhook.
- Indicador no painel: “Última sincronização com Agenda: …” / aviso se falhou.

---

### Fase C — UX e política de conflito

- Badge na agenda: “Sincronizado com Agenda” quando `AGENDAMENTO_IA_CLINIC_SYNC_URL` ativo.
- **Política explícita:** quem manda quando o painel ZA e o admin Agenda divergem? (Recomendação: **painel ZA = fonte de config** para tenants ZapAction; Agenda aceita snapshot como overwrite; ou documentar o contrário.)
- Cancelamento no painel ZA: se o registo veio do Agenda, chamar API Agenda para cancelar **ou** apenas atualizar Supabase e eventual inconsistência — **decidir** e implementar um caminho.

---

### Fase D — Motor único de leitura (futuro, só se necessário)

- Se quiserem **uma** lista de agendamentos sempre igual ao Agenda **sem** duplicar storage: endpoint no Agenda + UI no ZA em iframe/API (maior refactor). Só se o modelo “espelho no Supabase” não chegar.

---

## 4. Segurança e operações

- Segredos apenas em `.env` / vault; rotação documentada.
- Allowlist de IP (opcional) entre VMs.
- Logs correlacionados (`cliente_id`, `appointment_id`, `request_id`).

---

## 5. Checklist de tarefas (implementação)

- [x] Agenda: hook pós-commit em **criação** e **cancelamento** → cliente HTTP assíncrono + retries (`zapaction_outbound` + `booking_core` / `internal.cancel` / fluxos Google em `orchestrator` e `link_booking`).
- [ ] Agenda: hook em **remarcação** de `AppointmentRow` (todos os caminhos que alterem início/fim).
- [x] Agenda: variáveis `ZAPACTION_APPOINTMENT_WEBHOOK_URL` e `ZAPACTION_WEBHOOK_SECRET` documentadas em `.env.example`.
- [x] ZapAction: rota webhook + validação HMAC + upsert Supabase + migração `external_agenda_appointment_id`.
- [x] ZapAction: testes unitários da assinatura e parsing JSON (`tests/test_agendamento_ia_appointment_webhook.py`); alargar a payloads completos e idempotência é desejável.
- [ ] Documentar fluxo no README ou runbook interno (ambos os repositórios / deploy).
- [ ] (Opcional) Fase B job + endpoint export read-only no Agenda.
- [ ] Endurecimento: validar `cliente_id` (tenant existe) no receptor; teste fim-a-fim documentado.

---

## 6. Relação com outros planos

- **Cursor** (`api_vs_bd_partilhado`…): registo histórico da decisão “sem BD partilhado”.
- **`plano_tecnico_continuacao_zapaction_agenda.md`:** plano de **execução técnica** (contratos, ficheiros, segurança, prompt).
- **Este ficheiro:** plano de **produto e âmbito** (o quê entra na agenda no painel, fases A–D, riscos). Não há conflito: um descreve *valor e escopo*, o outro *como implementar*.

---

## 7. Riscos e mitigação

| Risco | Mitigação |
|-------|-----------|
| Webhook perdido | Idempotência + retry no Agenda + reconciliação (Fase B) |
| Duplo writer (ZA e Agenda) | Política de conflito (Fase C); cancelamentos sempre propagados |
| Payload desalinhado | `request_schema_version` e testes de contrato |

---

*Documento vivo: atualizar após cada fase concluída.*
