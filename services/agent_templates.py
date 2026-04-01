# services/agent_templates.py
# Templates de roteiro e regras negativas por tipo de agente.
# O front preenche os campos ao selecionar o tipo; o usuário pode editar antes de salvar.

AGENT_TEMPLATES = {
    "vendas": {
        "nome": "Vendas",
        "roteiro": [
            {"slug": "saudacao", "pergunta": "Cumprimente e pergunte em que pode ajudar.", "obrigatorio": True, "chave_memoria": None},
            {"slug": "nome", "pergunta": "Qual seu nome?", "obrigatorio": True, "chave_memoria": "nome"},
            {"slug": "email", "pergunta": "Qual seu e-mail?", "obrigatorio": True, "chave_memoria": "email"},
            {"slug": "telefone", "pergunta": "Qual seu telefone?", "obrigatorio": True, "chave_memoria": "telefone"},
            {"slug": "fechamento", "pergunta": "Envie o link ou feche a venda conforme o objetivo da empresa.", "obrigatorio": False, "chave_memoria": None},
        ],
        "regras_negativas": [
            "Nunca dar desconto ou condições especiais por conta própria.",
            "Nunca simular valores sem os dados oficiais da empresa.",
        ],
    },
    "suporte": {
        "nome": "Suporte / Atendimento",
        "roteiro": [
            {"slug": "saudacao", "pergunta": "Cumprimente e pergunte qual o problema ou dúvida.", "obrigatorio": True, "chave_memoria": None},
            {"slug": "entender", "pergunta": "Entenda o problema do cliente e tente resolver com a base de conhecimento.", "obrigatorio": True, "chave_memoria": None},
            {"slug": "resolver_ou_transferir", "pergunta": "Resolva ou oriente a falar com humano (link de transbordo) se não puder resolver.", "obrigatorio": False, "chave_memoria": None},
        ],
        "regras_negativas": [
            "Nunca prometer prazos ou soluções que não estejam no manual da empresa.",
            "Não inventar procedimentos; oriente falar com humano quando não souber.",
        ],
    },
    "agendamento": {
        "nome": "Agendamento",
        "roteiro": [
            {"slug": "saudacao", "pergunta": "Cumprimente e pergunte qual serviço ou data o cliente deseja.", "obrigatorio": True, "chave_memoria": None},
            {"slug": "servico_data", "pergunta": "Colete o tipo de serviço e a data/horário desejados (e nome/telefone se necessário).", "obrigatorio": True, "chave_memoria": None},
            {"slug": "confirmacao", "pergunta": "Confirme o agendamento e envie o link ou próximo passo.", "obrigatorio": False, "chave_memoria": None},
        ],
        "regras_negativas": [
            "Não confirmar horários que não estejam na disponibilidade oficial.",
            "Não criar compromissos sem os dados mínimos (serviço, data, contato).",
        ],
    },
}


def get_template(tipo: str):
    """Retorna o template do tipo ou None."""
    return AGENT_TEMPLATES.get(tipo) if tipo else None


def list_tipos():
    """Lista os tipos disponíveis (chaves do dicionário)."""
    return list(AGENT_TEMPLATES.keys())
