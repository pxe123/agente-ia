# Flow Builder (React + React Flow)

Editor visual de fluxos para o ZapAction. Os fluxos são executados pelo backend como máquina de estados (WhatsApp/Evolution ou Meta com mensagens interativas).

## Desenvolvimento

```bash
cd flow-builder
npm install
npm run dev
```

Acesse o painel em `http://localhost:5000`, faça login e abra `/flow`. Em dev, use o proxy do Vite ou rode o Flask na mesma origem.

## Build para produção

```bash
cd flow-builder
npm install
npm run build
```

O build gera os arquivos em `panel/static/flow-builder/`. O Flask serve em `/flow` e `/flow/<path>`.

## Funcionalidades

- **Nós**: Mensagem (texto + até 3 botões), Condição, Ação
- **Auto-save**: debounce de 3 segundos ao mover ou editar nós/conexões
- **Validação**: não permite salvar se houver nós sem conexão
- **Backend**: `FlowExecutor` persiste o nó atual por (cliente, canal, remote_id) e envia mensagens com botões (Meta interactive ou WAHA texto numerado)

## Compatibilidade

Apenas dependências JavaScript (sem binários nativos). Compatível com **aarch64** (Oracle Cloud Ampere).
