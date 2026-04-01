# Checklist de Testes - Refatoracao Segura

## Como usar
- Execute este checklist ao final de cada etapa.
- Marque apenas quando validar de fato.
- Se algum item falhar, registre no `docs/REFATORACAO.md` e nao avance.

## Basico do Chat
- [ ] A rota `/chat` abre sem travar no primeiro carregamento.
- [ ] Lista de conversas aparece corretamente.
- [ ] Abrir uma conversa carrega historico sem erro.
- [ ] Enviar mensagem de texto funciona.
- [ ] Receber mensagem funciona em tempo real.
- [ ] Scroll do chat permanece estavel (sem pulo inesperado).

## Midias e Entrada
- [ ] Envio de anexo (imagem/arquivo) funciona.
- [ ] Envio de audio funciona.
- [ ] Shift+Enter cria quebra de linha no input.
- [ ] Enter envia mensagem (sem quebrar comportamento esperado).

## Estado e Notificacoes
- [ ] Badges de nao lidas atualizam corretamente.
- [ ] Marcar conversa como lida funciona.
- [ ] Notificacao sonora respeita configuracao ligada/desligada.
- [ ] Notificacao desktop (quando permitida) continua funcionando.

## Integridade Visual
- [ ] Nao ha quebra visual em `chat.html`.
- [ ] Nao ha quebra visual em `inicio.html`.
- [ ] Nao ha quebra visual em `precos.html`.
- [ ] Header publico permanece com o visual aprovado.

## Console e Rede
- [ ] Sem erros novos no console.
- [ ] Sem loops de requests inesperados no primeiro load do `/chat`.
- [ ] Endpoints criticos respondem sem erro (4xx/5xx inesperado).

## Registro da Etapa
- [ ] Metricas antes/depois registradas no `docs/REFATORACAO.md`.
- [ ] Decisoes e trade-offs registrados no `docs/DECISOES.md`.
- [ ] Commit da etapa realizado com mensagem clara.

