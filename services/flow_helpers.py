# services/flow_helpers.py
"""
Funções puras do Flow Builder: parsing de nós/edges, match de botões, condições, questionário.
Sem dependência de DB nem de MessageService/RoutingService.
"""
from __future__ import annotations

import re

# Chave interna em collected_data para lista de campos que ainda estamos coletando (respostas do questionário)
PENDING_COLLECT_KEYS = "__pending_keys"

# Palavras que o usuário pode digitar para reiniciar o atendimento e sair do fluxo travado
REINICIAR_KEYWORDS = ("reiniciar", "/reiniciar", "encerrar", "sair", "reiniciar atendimento", "começar de novo", "início", "inicio")


def canal_to_channel(canal: str) -> str:
    """Mapeia canal do webhook para channel do fluxo."""
    if canal == "facebook":
        return "messenger"
    if canal in ("whatsapp", "instagram", "messenger", "website", "default", "welcome"):
        return canal
    return "default"


def is_reiniciar_comando(texto: str) -> bool:
    return (texto or "").strip().lower() in REINICIAR_KEYWORDS


def nodes_and_edges(flow_json: dict) -> tuple[list, list]:
    nodes = flow_json.get("nodes") or []
    edges = flow_json.get("edges") or []
    if not isinstance(nodes, list):
        nodes = []
    if not isinstance(edges, list):
        edges = []
    return nodes, edges


def node_by_id(nodes: list, node_id: str) -> dict | None:
    for n in nodes:
        if isinstance(n, dict) and n.get("id") == node_id:
            return n
    return None


def entry_node_id(nodes: list, edges: list) -> str | None:
    """Nó de entrada: sem arestas apontando para ele (target). Preferir tipo 'start' se existir."""
    targets = {e.get("target") for e in edges if isinstance(e, dict) and e.get("target")}
    candidates = []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        nid = n.get("id")
        if nid and nid not in targets:
            candidates.append((n.get("type"), nid))
    if not candidates:
        return nodes[0].get("id") if nodes and isinstance(nodes[0], dict) else None
    for typ, nid in candidates:
        if typ == "start":
            return nid
    return candidates[0][1]


def match_button_response(node: dict, user_text: str) -> str | None:
    """
    Retorna o sourceHandle do botão que corresponde à resposta do usuário.
    Match: (1) id do botão, (2) título do botão, (3) "1"/"2"/"3" por posição.
    """
    buttons = (node.get("data") or {}).get("buttons") or []
    if not buttons or not user_text:
        return None
    user = (user_text or "").strip().lower()
    for i, b in enumerate(buttons[:3]):
        if not isinstance(b, dict):
            continue
        bid = (b.get("id") or f"btn_{i}").strip()
        bid_lower = bid.lower()
        title = (b.get("title") or b.get("label") or "").strip().lower()
        if user == bid_lower or (title and user == title):
            return bid
        if user in ("1", "2", "3") and i + 1 == int(user):
            return bid
    return None


def evaluate_condition(rule: str, value: str, user_text: str) -> bool:
    """Avalia a condição: True = sim, False = não."""
    rule = (rule or "").strip().lower().replace(" ", "_")
    val = (value or "").strip().lower()
    user = (user_text or "").strip().lower()
    if not rule:
        return True
    if rule in ("contém", "contem", "contains"):
        return val in user if val else False
    if rule in ("igual", "equals", "exact"):
        return user == val
    if rule in ("começa_com", "comeca_com", "starts_with"):
        return user.startswith(val) if val else False
    return True


def find_next_node_id(nodes: list, edges: list, current_node_id: str, user_response_text: str) -> str | None:
    """
    Encontra o próximo nó a partir da resposta do usuário (botão ou texto).
    - Nó condition: avalia rule/value e retorna target da edge sim/nao.
    - Nó com botões: match por id/título/"1"/"2"/"3"; edge com sourceHandle=id do botão.
    - Senão: primeira edge com source=current (fluxo linear).
    """
    node = node_by_id(nodes, current_node_id)
    if not node:
        return None
    node_type = (node.get("type") or "").strip().lower()
    data = node.get("data") or {}

    if node_type == "condition":
        rule = data.get("rule") or data.get("ruleType") or ""
        value = data.get("value") or data.get("ruleValue") or ""
        result = evaluate_condition(rule, value, user_response_text or "")
        handle_wanted = "sim" if result else "nao"
        for e in edges:
            if not isinstance(e, dict) or e.get("source") != current_node_id:
                continue
            if (e.get("sourceHandle") or "").strip().lower() == handle_wanted:
                return e.get("target")
        for e in edges:
            if isinstance(e, dict) and e.get("source") == current_node_id and e.get("target"):
                return e.get("target")
        return None

    buttons = data.get("buttons") or []
    outgoing_edges = [
        e for e in edges
        if isinstance(e, dict) and e.get("source") == current_node_id and e.get("target")
    ]
    if not outgoing_edges:
        return None

    user_txt = (user_response_text or "").strip().lower()
    source_handle = None
    wanted_btn_index: int | None = None

    if buttons and user_txt:
        source_handle = match_button_response(node, (user_response_text or "").strip())

        # Se o usuário respondeu "1/2/3", conseguimos o índice diretamente.
        if user_txt in ("1", "2", "3"):
            wanted_btn_index = int(user_txt) - 1
        elif source_handle is not None:
            # Caso contrário, tenta inferir o índice pelo id do botão.
            for idx, b in enumerate((buttons or [])[:3]):
                if not isinstance(b, dict):
                    continue
                bid = (b.get("id") or f"btn_{idx}") or ""
                if bid.strip().lower() == str(source_handle).strip().lower():
                    wanted_btn_index = idx
                    break

    # 1) Tentativa principal: edge cujo sourceHandle corresponde ao handle do botão.
    if source_handle is not None:
        wanted_sh = str(source_handle).strip().lower()
        for e in outgoing_edges:
            e_handle = e.get("sourceHandle")
            if str(e_handle or "").strip().lower() == wanted_sh:
                return e.get("target")

        # 2) Se não achar sourceHandle, tenta resolver pelo índice do botão.
        if wanted_btn_index is not None:
            # Prefere edges "default" (sem sourceHandle) porque são as mais prováveis quando sourceHandle foi perdido.
            default_candidates = [
                e for e in outgoing_edges
                if not str(e.get("sourceHandle") or "").strip()
            ]
            if len(default_candidates) > wanted_btn_index:
                return default_candidates[wanted_btn_index].get("target")
            if len(outgoing_edges) > wanted_btn_index:
                return outgoing_edges[wanted_btn_index].get("target")

    # 3) Se não achou match de botão (ou não temos source_handle), tenta edge default.
    #    Isso evita o comportamento antigo de sempre escolher a primeira edge arbitrariamente.
    default_edges = [
        e for e in outgoing_edges
        if not str(e.get("sourceHandle") or "").strip()
    ]
    if default_edges:
        return default_edges[0].get("target")

    # Último recurso: se só existe uma saída, segue ela.
    if len(outgoing_edges) == 1:
        return outgoing_edges[0].get("target")

    return None


def questionnaire_collect_keys(data: dict) -> list:
    """Retorna lista de chaves para coleta a partir do nó questionário."""
    question_keys = data.get("questionKeys") or data.get("question_keys")
    if isinstance(question_keys, list) and question_keys:
        return [str(k).strip().lower() or f"campo_{i+1}" for i, k in enumerate(question_keys)]
    questions = data.get("questions") or []
    if not isinstance(questions, list):
        questions = []
    n = len(questions)
    return [f"campo_{i+1}" for i in range(n)]


def format_questionnaire_message(data: dict) -> str:
    """Formata intro + perguntas do nó questionário em uma única mensagem."""
    intro = (data.get("intro") or "").strip()
    questions = data.get("questions") or []
    if not isinstance(questions, list):
        questions = []
    lines = []
    if intro:
        lines.append(intro)
    for i, q in enumerate(questions):
        if isinstance(q, str) and q.strip():
            lines.append(f"{i + 1}. {q.strip()}")
    return "\n\n".join(lines) if lines else " "


def collected_data_for_lead(collected_data: dict, pending_key: str = PENDING_COLLECT_KEYS) -> dict:
    """Retorna cópia dos dados coletados sem chaves internas (ex.: __pending_keys)."""
    if not isinstance(collected_data, dict):
        return {}
    return {k: v for k, v in collected_data.items() if k != pending_key}


def next_node_after(node_id: str, edges: list) -> str | None:
    """Retorna o target da primeira edge que sai do node_id."""
    for e in edges:
        if isinstance(e, dict) and e.get("source") == node_id:
            return e.get("target")
    return None


def get_questionnaire_lead_sequence(
    nodes: list, edges: list, first_node_id: str
) -> tuple[str | None, list[str], str | None]:
    """
    Dado o primeiro nó após o start: se for questionnaire, percorre a sequência
    e retorna (questionnaire_node_id, lista de lead_node_ids, next_node_id_after_leads).
    Se first_node_id não for questionnaire, retorna (None, [], first_node_id).
    """
    node = node_by_id(nodes, first_node_id)
    if not node or (node.get("type") or "").strip().lower() != "questionnaire":
        return (None, [], first_node_id)
    questionnaire_id = first_node_id
    lead_ids: list[str] = []
    current_id: str | None = next_node_after(first_node_id, edges)
    while current_id:
        n = node_by_id(nodes, current_id)
        if not n:
            return (questionnaire_id, lead_ids, current_id)
        ntype = (n.get("type") or "").strip().lower()
        if ntype != "lead":
            return (questionnaire_id, lead_ids, current_id)
        lead_ids.append(current_id)
        current_id = next_node_after(current_id, edges)
    return (questionnaire_id, lead_ids, None)


# Regex para extrair email e telefone de mensagem livre (ex.: "Ricardo 1ricardo@gmail.com 14996755366")
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}"
)
# Telefone BR - aceita código do país (55) + DDD + número, ou só DDD + número.
# Exemplos suportados (todos normalizados para 14996755366):
#   5514996755366  55 14 996755366  55 (14) 99675-5366  (14)99675-5366
#   14996755366  14 99675-5366  55 14 99675 5366  55 14 99675-5366
_PHONE_RE = re.compile(
    r"(?:\+?55[\s.]*)?(?:\(?\s*)?(\d{2})\s*[\)]?\s*[\s.\-]*(\d{4,5})\s*[\s.\-]*(\d{4})"
)
_PHONE_PLAIN_RE = re.compile(
    r"(?:\+?55[\s.]*)?(\d{2})[\s.]*(\d{8,9})\b"
)


def parse_lead_from_text(texto: str) -> dict[str, str]:
    """
    Extrai nome, email e telefone de uma mensagem livre.
    Ex.: "Ricardo 1ricardodetomasi@gmail.com 14996755366" -> {nome, email, telefone}.
    Retorno: dict com chaves "nome", "email", "telefone" (vazio se não encontrado).
    """
    texto = (texto or "").strip()
    if not texto:
        return {"nome": "", "email": "", "telefone": ""}
    out: dict[str, str] = {"nome": "", "email": "", "telefone": ""}
    print(f"[LEAD] parse_lead_from_text entrada: {(texto[:80] + '...') if len(texto) > 80 else texto!r}", flush=True)
    # Email
    m = _EMAIL_RE.search(texto)
    if m:
        out["email"] = m.group(0).strip()
    # Telefone (celular BR: 2 DDD + 9 dígitos ou fixo 2 + 8)
    m = _PHONE_RE.search(texto)
    if m:
        ddd, part1, part2 = m.group(1), m.group(2), m.group(3)
        out["telefone"] = f"{ddd}{part1}{part2}"
    else:
        m = _PHONE_PLAIN_RE.search(texto)
        if m:
            out["telefone"] = m.group(1) + m.group(2)
    # Nome: o que sobra removendo email e telefone (trim); ou texto antes do email se rest vazio
    rest = texto
    if out["email"]:
        rest = rest.replace(out["email"], " ", 1)
    if out["telefone"]:
        rest = _PHONE_RE.sub(" ", rest, count=1)
        rest = _PHONE_PLAIN_RE.sub(" ", rest, count=1)
    rest = " ".join(rest.split()).strip()
    if rest:
        out["nome"] = re.sub(r"^[\s,;.\-]+|[\s,;.\-]+$", "", rest).strip() or rest
    elif out["email"] and not out["nome"]:
        idx = texto.find(out["email"])
        if idx > 0:
            antes = texto[:idx].strip()
            if antes and not re.search(r"\d{10,}", antes):
                out["nome"] = re.sub(r"^[\s,;.\-]+|[\s,;.\-]+$", "", " ".join(antes.split())).strip()
    print(f"[LEAD] parse_lead_from_text saida: nome={out['nome']!r} email={out['email']!r} telefone={out['telefone']!r}", flush=True)
    return out
