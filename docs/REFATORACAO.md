# Projeto de Refatoracao Segura - SaaS Chat

## Objetivo
Refatorar o sistema de forma incremental, sem quebrar comportamento em producao, com controle de risco, rastreabilidade e continuidade entre sessoes.

## Regras Operacionais (obrigatorias)
- Nao alterar multiplas areas criticas na mesma etapa.
- Nao misturar frontend e backend na mesma mudanca quando a etapa nao pedir isso.
- Nao remover codigo antigo sem ter substituto validado.
- Um commit por etapa concluida.
- Toda etapa precisa registrar metricas antes/depois e resultado de testes.

## Convencao de Status
- `PENDENTE`
- `EM_ANDAMENTO`
- `CONCLUIDA`
- `BLOQUEADA`

## Linha de execucao definida (sem novas etapas)
1. ETAPA 0 - Preparacao
2. ETAPA 1 - Isolar renderizacao de mensagens
3. ETAPA 2 - Isolar envio de mensagens
4. ETAPA 3 - Isolar chamadas API
5. ETAPA 4 - Separar estado do chat
6. ETAPA 5 - Realtime (socket + polling)
7. ETAPA 6 - Limpeza final do chat.js
8. ETAPA 7 - Backend services
9. ETAPA 8 - Queries
10. ETAPA 9 - Templates

---

## Painel de Controle

### Status Atual
- Etapa atual: `ETAPA_0`
- Status atual: `PENDENTE`
- Ultima atualizacao: `____/____/______ ____:____`
- Responsavel: `________________`
- Branch atual: `________________`

### Proxima Acao
- `Definir baseline de metricas e checklist de testes`

---

## Baseline Global (antes de iniciar ETAPA 1)

### Ambiente
- URL base: `________________`
- Navegador: `________________`
- Data/hora medicao: `____/____/______ ____:____`

### Metricas iniciais (global)
- Tempo ate abrir `/chat`: `__________`
- Numero de requests no primeiro load do `/chat`: `__________`
- Erros JS em console no primeiro load: `__________`
- Tempo de envio de mensagem (media de 3 testes): `__________`
- Falhas de envio (3 testes): `__________`

### Resultado baseline
- Observacoes: `________________________________________________________`

---

## Template obrigatorio por etapa

Use este bloco em todas as etapas:

### Escopo da etapa
- Objetivo:
- Arquivos permitidos:
- O que NAO pode ser alterado:

### Definicao de Pronto (DoD)
- [ ] Comportamento funcional preservado
- [ ] Sem erro novo no console
- [ ] Checklist de teste da etapa 100% executado
- [ ] Metricas antes/depois registradas
- [ ] Diff revisado e dentro do escopo da etapa
- [ ] Commit realizado com mensagem da etapa

### Rollback da etapa
- Comando/acao de rollback:
- Condicao de acionamento do rollback:
- Resultado esperado apos rollback:

### Metricas da etapa (antes/depois)
- Antes:
- Depois:
- Variacao:

### Evidencias
- Commits:
- Arquivos alterados:
- Logs/prints:

### Resultado
- Status final:
- Riscos residuais:
- Proxima etapa:

---

## ETAPA 0 - Preparacao

Status: `PENDENTE`

### Escopo da etapa
- Objetivo: preparar metodo, baseline, branch e checklist para execucao segura.
- Arquivos permitidos: `docs/REFATORACAO.md` e documentos de apoio.
- O que NAO pode ser alterado: codigo funcional do sistema.

### Definicao de Pronto (DoD)
- [ ] Baseline global preenchido
- [ ] Checklist de testes definido
- [ ] Branch de trabalho criada
- [ ] Estrutura deste arquivo validada
- [ ] Critrios de rollback definidos para etapas 1-9

### Rollback da etapa
- Comando/acao de rollback: descartar apenas ajustes de documentacao desta etapa.
- Condicao de acionamento do rollback: documento inconsistente ou incompleto.
- Resultado esperado apos rollback: retornar ao documento anterior sem impacto no codigo.

### Metricas da etapa (antes/depois)
- Antes: `N/A (preparacao)`
- Depois: `N/A (preparacao)`
- Variacao: `N/A`

### Evidencias
- Commits:
- Arquivos alterados:
- Logs/prints:

### Resultado
- Status final:
- Riscos residuais:
- Proxima etapa:

---

## ETAPA 1 - Isolar renderizacao de mensagens

Status: `PENDENTE`

### Escopo da etapa
- Objetivo: extrair somente a parte de renderizacao de mensagens.
- Arquivos permitidos: modulos de frontend do chat e pontos de integracao direta.
- O que NAO pode ser alterado: regras de envio, realtime, backend e contratos de API.

### Definicao de Pronto (DoD)
- [ ] Renderizacao movida para modulo dedicado
- [ ] Fluxo visual igual ao anterior
- [ ] Sem regressao em abertura de conversa e rolagem
- [ ] Testes manuais da etapa aprovados
- [ ] Metricas antes/depois registradas
- [ ] Commit da etapa realizado

### Rollback da etapa
- Comando/acao de rollback: reverter commit da ETAPA 1.
- Condicao de acionamento do rollback: regressao visual/funcional nas mensagens.
- Resultado esperado apos rollback: renderizacao volta ao estado anterior estavel.

### Metricas da etapa (antes/depois)
- Antes:
- Depois:
- Variacao:

### Evidencias
- Commits:
- Arquivos alterados:
- Logs/prints:

### Resultado
- Status final:
- Riscos residuais:
- Proxima etapa:

---

## ETAPA 2 - Isolar envio de mensagens

Status: `PENDENTE`

### Escopo da etapa
- Objetivo: separar apenas o fluxo de envio de mensagens.
- Arquivos permitidos: frontend do chat relacionado a input/envio.
- O que NAO pode ser alterado: renderizacao ja estabilizada na etapa 1 e backend.

### Definicao de Pronto (DoD)
- [ ] Envio manual isolado em modulo proprio
- [ ] Anexo/audio continuam funcionando
- [ ] Sem duplicacao de mensagens apos envio
- [ ] Testes manuais da etapa aprovados
- [ ] Metricas antes/depois registradas
- [ ] Commit da etapa realizado

### Rollback da etapa
- Comando/acao de rollback: reverter commit da ETAPA 2.
- Condicao de acionamento do rollback: falha de envio, duplicacao, perda de UX.
- Resultado esperado apos rollback: envio volta ao estado anterior estavel.

### Metricas da etapa (antes/depois)
- Antes:
- Depois:
- Variacao:

### Evidencias
- Commits:
- Arquivos alterados:
- Logs/prints:

### Resultado
- Status final:
- Riscos residuais:
- Proxima etapa:

---

## ETAPA 3 - Isolar chamadas API

Status: `PENDENTE`

### Escopo da etapa
- Objetivo: centralizar chamadas HTTP do chat em modulo dedicado.
- Arquivos permitidos: frontend de API do chat e integracoes diretas.
- O que NAO pode ser alterado: contratos dos endpoints backend.

### Definicao de Pronto (DoD)
- [ ] Fetches centralizados
- [ ] Tratamento de erro padronizado
- [ ] Sem alteracao de payload esperado
- [ ] Testes manuais da etapa aprovados
- [ ] Metricas antes/depois registradas
- [ ] Commit da etapa realizado

### Rollback da etapa
- Comando/acao de rollback: reverter commit da ETAPA 3.
- Condicao de acionamento do rollback: falhas de carga/envio por erro de contrato.
- Resultado esperado apos rollback: chamadas HTTP no formato anterior.

### Metricas da etapa (antes/depois)
- Antes:
- Depois:
- Variacao:

### Evidencias
- Commits:
- Arquivos alterados:
- Logs/prints:

### Resultado
- Status final:
- Riscos residuais:
- Proxima etapa:

---

## ETAPA 4 - Separar estado do chat

Status: `PENDENTE`

### Escopo da etapa
- Objetivo: reduzir variaveis globais e centralizar estado.
- Arquivos permitidos: frontend de estado do chat e consumidores diretos.
- O que NAO pode ser alterado: regra de negocio de backend.

### Definicao de Pronto (DoD)
- [ ] Estado centralizado em modulo
- [ ] Sem regressao em abertura/fechamento de conversa
- [ ] Sem regressao em unread/badges
- [ ] Testes manuais da etapa aprovados
- [ ] Metricas antes/depois registradas
- [ ] Commit da etapa realizado

### Rollback da etapa
- Comando/acao de rollback: reverter commit da ETAPA 4.
- Condicao de acionamento do rollback: estado inconsistente, badges errados, conversa ativa errada.
- Resultado esperado apos rollback: estado volta ao gerenciamento anterior estavel.

### Metricas da etapa (antes/depois)
- Antes:
- Depois:
- Variacao:

### Evidencias
- Commits:
- Arquivos alterados:
- Logs/prints:

### Resultado
- Status final:
- Riscos residuais:
- Proxima etapa:

---

## ETAPA 5 - Realtime (socket + polling)

Status: `PENDENTE`

### Escopo da etapa
- Objetivo: organizar realtime com socket principal e polling fallback.
- Arquivos permitidos: modulo realtime frontend e pontos de inicializacao.
- O que NAO pode ser alterado: comportamento funcional de entrega de mensagem.

### Definicao de Pronto (DoD)
- [ ] Socket como canal principal
- [ ] Polling como fallback validado
- [ ] Sem duplicacao de mensagens
- [ ] Sem perda de notificacao
- [ ] Testes manuais da etapa aprovados
- [ ] Metricas antes/depois registradas
- [ ] Commit da etapa realizado

### Rollback da etapa
- Comando/acao de rollback: reverter commit da ETAPA 5.
- Condicao de acionamento do rollback: perda de tempo real, duplicacao ou atraso severo.
- Resultado esperado apos rollback: fluxo realtime anterior restaurado.

### Metricas da etapa (antes/depois)
- Antes:
- Depois:
- Variacao:

### Evidencias
- Commits:
- Arquivos alterados:
- Logs/prints:

### Resultado
- Status final:
- Riscos residuais:
- Proxima etapa:

---

## ETAPA 6 - Limpeza final do chat.js

Status: `PENDENTE`

### Escopo da etapa
- Objetivo: remover sobras apos extracoes anteriores e manter bootstrap limpo.
- Arquivos permitidos: frontend do chat ja modularizado.
- O que NAO pode ser alterado: contratos entre modulos validados nas etapas 1-5.

### Definicao de Pronto (DoD)
- [ ] Codigo legado removido com seguranca
- [ ] chat.js reduzido para orquestracao/bootstrap
- [ ] Sem regressao funcional global do chat
- [ ] Testes manuais da etapa aprovados
- [ ] Metricas antes/depois registradas
- [ ] Commit da etapa realizado

### Rollback da etapa
- Comando/acao de rollback: reverter commit da ETAPA 6.
- Condicao de acionamento do rollback: regressao nao mapeada apos limpeza.
- Resultado esperado apos rollback: versao modular anterior (pre-limpeza) recuperada.

### Metricas da etapa (antes/depois)
- Antes:
- Depois:
- Variacao:

### Evidencias
- Commits:
- Arquivos alterados:
- Logs/prints:

### Resultado
- Status final:
- Riscos residuais:
- Proxima etapa:

---

## ETAPA 7 - Backend services

Status: `PENDENTE`

### Escopo da etapa
- Objetivo: separar regras de negocio das rotas em camada de servico.
- Arquivos permitidos: rotas backend e camada de servicos/repositorio relacionada.
- O que NAO pode ser alterado: contratos HTTP externos sem necessidade.

### Definicao de Pronto (DoD)
- [ ] Rotas mais finas (delegando para servicos)
- [ ] Regras centrais movidas para services
- [ ] Sem alteracao de resposta HTTP esperada
- [ ] Testes manuais da etapa aprovados
- [ ] Metricas antes/depois registradas
- [ ] Commit da etapa realizado

### Rollback da etapa
- Comando/acao de rollback: reverter commit da ETAPA 7.
- Condicao de acionamento do rollback: regressao em endpoints do chat.
- Resultado esperado apos rollback: rotas voltam ao formato anterior estavel.

### Metricas da etapa (antes/depois)
- Antes:
- Depois:
- Variacao:

### Evidencias
- Commits:
- Arquivos alterados:
- Logs/prints:

### Resultado
- Status final:
- Riscos residuais:
- Proxima etapa:

---

## ETAPA 8 - Queries

Status: `PENDENTE`

### Escopo da etapa
- Objetivo: otimizar consultas (evitar overfetch, melhorar latencia).
- Arquivos permitidos: backend de consultas e migracoes/indices relacionados.
- O que NAO pode ser alterado: semantica funcional de negocio.

### Definicao de Pronto (DoD)
- [ ] Reducao de overfetch (evitar `select *` onde nao precisa)
- [ ] Paginacao/indices aplicados conforme escopo
- [ ] Latencia dos endpoints criticos reduzida ou estabilizada
- [ ] Testes manuais da etapa aprovados
- [ ] Metricas antes/depois registradas
- [ ] Commit da etapa realizado

### Rollback da etapa
- Comando/acao de rollback: reverter commit da ETAPA 8 (codigo e scripts desta etapa).
- Condicao de acionamento do rollback: piora de latencia, erro de consulta, regressao funcional.
- Resultado esperado apos rollback: consultas e performance retornam ao baseline anterior.

### Metricas da etapa (antes/depois)
- Antes:
- Depois:
- Variacao:

### Evidencias
- Commits:
- Arquivos alterados:
- Logs/prints:

### Resultado
- Status final:
- Riscos residuais:
- Proxima etapa:

---

## ETAPA 9 - Templates

Status: `PENDENTE`

### Escopo da etapa
- Objetivo: reduzir duplicacao e organizar exibicao sem espalhar regra.
- Arquivos permitidos: templates Jinja e componentes de layout relacionados.
- O que NAO pode ser alterado: regra de negocio backend.

### Definicao de Pronto (DoD)
- [ ] Duplicacoes relevantes reduzidas
- [ ] Exibicao consistente entre paginas publicas e painel
- [ ] Sem regressao visual relevante
- [ ] Testes manuais da etapa aprovados
- [ ] Metricas antes/depois registradas
- [ ] Commit da etapa realizado

### Rollback da etapa
- Comando/acao de rollback: reverter commit da ETAPA 9.
- Condicao de acionamento do rollback: regressao visual ou quebra de template.
- Resultado esperado apos rollback: templates retornam ao estado anterior estavel.

### Metricas da etapa (antes/depois)
- Antes:
- Depois:
- Variacao:

### Evidencias
- Commits:
- Arquivos alterados:
- Logs/prints:

### Resultado
- Status final:
- Riscos residuais:
- Proxima etapa:

---

## Checklist Minimo de Teste (usar em todas as etapas)
- [ ] Abertura do `/chat` sem travamento critico
- [ ] Envio de mensagem (texto) funcionando
- [ ] Recebimento de mensagem em tempo real funcionando
- [ ] Upload de anexo funcionando
- [ ] Sem erro novo no console
- [ ] Sem quebra visual nas telas alteradas

---

## Historico de Mudancas

### Registro Padrao
- Data:
- Etapa:
- O que foi feito:
- Arquivos alterados:
- Resultado:
- Problemas encontrados:
- Acao de rollback necessaria?:

