# Pós-aprovação Google OAuth — ZapAction

Após o Google aprovar a verificação e o consent screen mostrar **In production** + verificado:

## 1. Validar em produção

1. Remover (ou não depender de) e-mails na lista **Test users** do Console
2. Com uma conta Google **não** listada como test user:
   - Login no painel ZapAction
   - Agenda → Profissionais → **Conectar Google**
   - Deve concluir sem ecrã bloqueando utilizadores externos
3. Confirmar que não aparece aviso persistente "Google hasn't verified this app" para utilizadores finais

```bash
cd ~/agente-ia && source venv/bin/activate
python scripts/verify_google_oauth_env.py
```

## 2. Reconectar profissionais existentes

Tokens emitidos em **Testing** ou com scopes antigos (`calendar` largo) podem precisar de nova autorização.

**Pedido aos clientes (modelo):**

> Olá! A integração com Google Calendar do ZapAction foi atualizada e aprovada pelo Google.  
> Por favor, no painel **Agenda → Profissionais**, clique em **Reconectar Google** para cada profissional que usa calendário.  
> Isso garante disponibilidade de horários e sincronização de marcações.  
> Se preferir revogar antes: https://myaccount.google.com/permissions

## 3. Desligar ligação (cliente)

No painel: Agenda → Profissionais → **Desligar Google**.

Também pode revogar em: https://myaccount.google.com/permissions

## 4. Monitorização

- Logs ZapAction: erros em `google_connect` / `google_callback`
- Agenda: `GET /v1/integrations/zapaction/google/status?cliente_id=...&provider_id=...`
- Sintoma comum pós-migração: `403` / `insufficientPermissions` em freebusy → **Reconectar Google**

## 5. Renovação

Scopes sensíveis podem exigir re-verificação periódica. Manter política de privacidade atualizada e vídeo demo arquivado para resubmissão.
