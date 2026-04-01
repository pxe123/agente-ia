# Plano: Pular cadastro quando lead já tem dados e gravar novamente na lista

## Objetivo

1. **Coleta de dados**: Considerar que o lead "já tem dados" quando existir **qualquer** lead (cliente_id + canal + remote_id) com nome, email e telefone preenchidos — **sem exigir status = qualificado**.
2. **Quando já tem dados**: Pular o questionário de cadastro e ir direto ao atendimento (próximo nó após o nó de lead).
3. **Gravar novamente**: Nesse caso, mesmo pulando o questionário, **inserir um novo registro na tabela `leads`** com os dados do lead existente, para que o retorno do contato conste na lista de leads (evitar duplicidade de perguntas, mas manter registro da interação).

---

## Escopo (o que NÃO muda)

- Fluxo atual de quem **não** tem dados: questionário → nó lead → _save_lead → próximo nó. Continua igual.
- Definição de "já tem dados": apenas presença de nome, email e telefone em algum lead do mesmo (cliente_id, canal, remote_id). **Status é ignorado** (pendente, qualificado ou desqualificado).

---

## Regras de negócio

| Situação | Ação |
|----------|------|
| Existe lead com (cliente_id, canal, remote_id) com nome, email e telefone preenchidos | Considerar "já cadastrado". Pular questionário, **gravar novo registro em leads** com esses dados, avançar fluxo para o nó após o(s) nó(s) de lead. |
| Não existe ou existe mas sem os três campos preenchidos | Seguir fluxo normal: enviar questionário, coletar respostas, _save_lead ao passar pelo nó lead. |

---

## Implementação

### 1. Função auxiliar: buscar lead existente com dados completos

**Onde:** `services/flow_executor.py` ou `services/flow_helpers.py` (se for só leitura de dados, helpers; se precisar de Supabase, executor).

**O que faz:**

- Consulta na tabela `leads`:
  - `cliente_id` = cliente_id
  - `canal` = canal
  - `remote_id` = remote_id
- Ordenar por `created_at` desc, limit 1 (ou buscar o mais recente com dados preenchidos).
- Retornar o registro **somente se** tiver `nome`, `email` e `telefone` não nulos/não vazios (trim).
- **Não** filtrar por `status` (qualificado não é exigido).

**Assinatura sugerida:**

```text
def get_existing_lead_with_data(cliente_id: str, canal: str, remote_id: str) -> dict | None
```

Retorno: linha do lead (dict) ou `None` se não houver ou se faltar algum dos três campos.

---

### 2. Descobrir a sequência “questionário → nó(s) lead” no fluxo

Para "pular" e ainda assim "gravar novamente", o executor precisa:

- Saber qual é o **primeiro nó após o start** (já existe: `entry_node_id` + primeira edge).
- Se esse nó for do tipo **questionnaire**, considerar que a sequência típica é:  
  `start → questionnaire → [lead] → [lead...] → próximo (message/action/end)`.
- Percorrer as edges a partir do nó de questionário até passar por todos os nós `type === "lead"` e obter o **próximo nó após o último lead** (target da edge que sai do último lead).

**Onde:** lógica nova no `FlowExecutor.process`, ou função auxiliar em `flow_helpers.py` que, dado o nó de entrada após o start, retorna:
- o nó do questionário (se for questionnaire),
- a lista de nós "lead" em sequência,
- e o **node_id** do próximo nó após o último lead (para onde pular).

Exemplo de assinatura (em helpers, sem Supabase):

```text
def get_questionnaire_lead_sequence(nodes, edges, first_node_after_start) -> tuple[str | None, list[str], str | None]
```
- Retorno: (questionnaire_node_id ou None, lista de lead_node_ids, next_node_id_after_leads).

Assim o executor sabe: "se já tenho dados, pulo do start direto para next_node_id_after_leads, e antes disso chamo _save_lead para cada nó lead com os dados do lead existente".

---

### 3. No início do fluxo (quando `current_node_id` é None ou vazio)

**Onde:** `FlowExecutor.process`, no bloco que trata "sem estado" / entrada (por volta das linhas 346–385).

**Ordem sugerida:**

1. Obter `entry_id` e o primeiro nó após o start (como hoje).
2. **Novo:** Se o primeiro nó for do tipo **questionnaire**:
   - Chamar `get_existing_lead_with_data(cliente_id, canal, remote_id)`.
   - Se retornar um lead com dados:
     - Obter a sequência questionnaire → leads → próximo nó (função do passo 2).
     - Para **cada** nó do tipo "lead" nessa sequência: chamar `_save_lead(cliente_id, canal, remote_id, flow_id, collected_data, node_data)` com `collected_data` montado a partir do lead existente (nome, email, telefone, e opcionalmente `dados` se existir). Isso **grava novamente na lista de leads** (novo insert).
     - Definir o estado do fluxo como se o usuário já tivesse passado pelo questionário e pelos nós lead: `set_state(cliente_id, canal, remote_id, flow_id, next_node_id_after_leads, collected_data)` (ou estado "limpo" se o próximo nó for end).
     - Enviar a mensagem do **próximo nó** (message/action/end) em vez do questionário (para não mostrar as perguntas de cadastro).
     - `return True`.
   - Se **não** retornar lead com dados: seguir como hoje (enviar questionário e continuar o fluxo).
3. Se o primeiro nó **não** for questionnaire, manter comportamento atual (enviar esse nó e setar estado).

Assim:
- Lead **não** precisa estar qualificado para pular o cadastro (só precisa ter nome, email, telefone).
- Sempre que pulamos, **gravamos novamente** na lista de leads com os dados do lead existente.

---

### 4. Montar `collected_data` a partir do lead existente

Para chamar `_save_lead` quando estamos "pulando" o questionário, precisamos de um `collected_data` no mesmo formato que o questionário preencheria. Exemplo:

```text
collected_data = {
    "nome": lead_row.get(LeadModel.NOME) or "",
    "email": lead_row.get(LeadModel.EMAIL) or "",
    "telefone": lead_row.get(LeadModel.TELEFONE) or "",
}
```
Se a tabela tiver um campo `dados` (JSON), podemos mesclar esse JSON em `collected_data` para não perder campos extras. O `_save_lead` já usa `collected_data_for_lead` e extrai nome/email/telefone; manter esse comportamento.

---

### 5. Evitar recursão / loop na primeira mensagem

Garantir que, ao "pular" e enviar o próximo nó (ex.: mensagem de boas-vindas ou fim), o estado fique consistente:
- `current_node_id` = próximo nó após os leads (ou None se for end e quisermos limpar).
- Na próxima mensagem do usuário, o fluxo seguirá a partir desse nó (botões, condições, etc.), sem voltar ao questionário.

---

### 6. Testes manuais sugeridos

1. **Primeiro contato (sem lead):** enviar mensagem → deve receber questionário → preencher → lead gravado → próximo nó. Nenhuma mudança de comportamento.
2. **Retorno com lead já preenchido (status pendente):** mesmo remote_id/canal → deve pular questionário, gravar **novo** registro em leads com os mesmos dados, e enviar o próximo nó (atendimento).
3. **Retorno com lead qualificado:** idem ao anterior (gravar novamente, pular questionário).
4. **Lead existente mas sem email:** não deve pular; deve mostrar questionário e coletar o que faltar (comportamento atual ou ajuste fino conforme desenho do questionário).

---

## Resumo dos arquivos a alterar

| Arquivo | Alteração |
|---------|-----------|
| `services/flow_executor.py` | (1) Chamada a `get_existing_lead_with_data`; (2) lógica de "pular questionário + gravar novamente + set_state + enviar próximo nó" quando há lead com dados; (3) uso da função que obtém a sequência questionnaire → leads → próximo nó. |
| `services/flow_helpers.py` (opcional) | Função `get_questionnaire_lead_sequence(nodes, edges, first_node_id)` para não poluir o executor. |
| `database` / Supabase | Nenhuma migração obrigatória; apenas consulta e insert na tabela `leads` já existente. |

---

## Ordem sugerida de desenvolvimento

1. Implementar `get_existing_lead_with_data` e testar a query isoladamente (ex.: script ou teste manual).
2. Implementar `get_questionnaire_lead_sequence` (ou equivalente) e testar com um flow_json de exemplo (start → questionnaire → lead → end).
3. No `FlowExecutor.process`, inserir o bloco "se primeiro nó é questionnaire e get_existing_lead_with_data retorna dados": montar collected_data, chamar _save_lead para cada nó lead, set_state, enviar próximo nó, return True.
4. Testes manuais (primeiro contato, retorno com dados, retorno sem dados).
5. Ajustes finos (mensagem exibida, estado após "end", etc.).

---

*Documento de plano — implementação a ser feita conforme este roteiro.*
