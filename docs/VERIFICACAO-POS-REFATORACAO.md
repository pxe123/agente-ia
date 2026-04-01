# Verificação pós-refatoração

Checklist para garantir que nada quebrou após as refatorações (reorganização de pastas, extração de helpers, padronização de estilo).

## 1. Comandos para subir o ambiente

### Backend (raiz do projeto)

```powershell
cd "C:\Users\Ricardo De Tomasi\Documents\app\agente-ia"
python app.py
```

- O app deve subir em **http://localhost:5000** (ou na porta definida em `PORT`).
- No terminal deve aparecer: `SaaS Multicanal iniciando no SocketIO...` e a URL do webhook Meta (se `WEBHOOK_URL` estiver no `.env`).

### Flow Builder – build para produção

```powershell
cd "C:\Users\Ricardo De Tomasi\Documents\app\agente-ia\flow-builder"
npm install
npm run build
```

- O build gera os arquivos em `panel/static/flow-builder/`.
- Não deve haver erros de compilação.

---

## 2. Rotas Flask (não mudaram)

Conferir que as URLs e métodos continuam os mesmos:

| Rota | Método | Uso |
|------|--------|-----|
| `/` | GET | Página inicial / redireciona para painel se logado |
| `/login` | GET, POST | Login |
| `/painel` | GET | Dashboard (logado) |
| `/chat` | GET | Chat (logado) |
| `/conexoes` | GET | Conexões Meta/WhatsApp (logado) |
| `/fluxos` | GET | Lista de fluxos (logado) |
| `/flow` | GET | Flow Builder (logado) |
| `/api/flows` | GET | Lista de fluxos (JSON) |
| `/api/flow` | GET, POST | Obter/salvar fluxo (query: `channel` ou `chatbot_id`) |
| `/api/flows/delete-all` | POST, DELETE | Apagar todos os fluxos do cliente |
| `/api/chatbots` | GET, POST | Listar/criar chatbots |
| `/api/chatbots/<id>` | GET, PATCH, DELETE | Um chatbot |
| `/api/enviar` | POST | Enviar mensagem manual (painel) |
| `/api/mensagens/<canal>` | GET | Histórico de mensagens |
| `/api/mensagens/contatos-nao-lidos` | GET | Contatos não lidos por canal |
| `/webhook/meta` | GET, POST | Webhook Meta (WhatsApp/Instagram/Messenger) |
| `/webhook/waha` | POST | Webhook WAHA |

Nenhuma dessas rotas foi alterada na refatoração; apenas organização interna e imports.

---

## 3. Testes manuais sugeridos

### 3.1 Login e painel

1. Abrir **http://localhost:5000**.
2. Fazer login com um usuário existente.
3. Verificar se o painel carrega (dashboard, menu lateral).
4. Clicar em **Chat** e ver se a tela do chat abre.
5. Clicar em **Conexões** e ver se a página de conexões carrega.

### 3.2 Flow Builder

1. Acessar **http://localhost:5000/flow** (logado).
2. Ver se o canvas do React Flow aparece.
3. Trocar de canal no dropdown (ex.: Default, WhatsApp) e ver se a lista de fluxos atualiza.
4. Criar um fluxo simples:
   - Arrastar **Início** → **Mensagem** → **Fim**.
   - Conectar as bolinhas (arrastar da direita de um nó até a esquerda do outro).
   - Preencher texto na mensagem.
5. Clicar em **Salvar** e ver se aparece mensagem de sucesso (e se não houver nós soltos).
6. Recarregar a página e trocar de canal e voltar: o fluxo salvo deve carregar de novo.

### 3.3 Recebimento de mensagem (se tiver canal configurado)

1. Com o app rodando, enviar uma mensagem por WhatsApp/Instagram/Messenger (conforme o que estiver configurado).
2. No terminal do backend, deve aparecer algo como:
   - `[MessageService] Mensagem salva: canal=...`
   - `[MessageService] Chamando FlowExecutor.process ...`
   - `[MessageService] FlowExecutor.process retornou handled=...`
3. No painel, em **Chat**, a mensagem deve aparecer no histórico (e o fluxo deve responder se estiver configurado).

### 3.4 Fluxo completo (Start → Mensagem → Questionário → Lead → Ação → End)

1. No Flow Builder, montar um fluxo com: **Start** → **Mensagem** (com ou sem botões) → **Questionário** (perguntas) → **Lead** → **Ação** (ex.: Transferir para humano ou Enviar link) → **End**.
2. Conectar todos os nós (nenhum nó solto).
3. Salvar.
4. Enviar mensagem no canal correspondente e seguir o fluxo: resposta da mensagem, respostas do questionário, e ver se a ação (transferência ou link) e a mensagem de fim são executadas.

---

## 4. Se algo falhar

- **Erro de import no Python**: verificar que está rodando na **raiz** do projeto (`python app.py` na pasta `agente-ia`), para que `services`, `panel`, `database`, `base`, `webhooks`, `integrations` sejam encontrados.
- **Flow Builder em branco ou 404**: rodar `npm run build` dentro de `flow-builder` e conferir se `panel/static/flow-builder/index.html` e os assets foram gerados.
- **Erro ao salvar fluxo**: verificar no navegador (F12 → Network) se o POST para `/api/flow` retorna 200 e se o body enviado está correto (ex.: `channel`, `flow_json`, `chatbot_id` quando for o caso).

---

## 5. Marcar verify-regression no plano

Após executar os passos acima e confirmar que está tudo certo, marque no plano `refatorar-estrutura-saaspainel` o item **verify-regression** como `completed`.
