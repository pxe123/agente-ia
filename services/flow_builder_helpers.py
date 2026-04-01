# services/flow_builder_helpers.py
"""
Helpers para o Flow Builder (painel): normalização e validação de flow_json, lista de canais.
Usado pelas rotas da API de fluxos em panel/routes/customer.py.
"""
import json


def normalize_flow_json(value) -> dict:
    """Garante que flow_json seja sempre um dict com nodes e edges (evita 500 quando o DB devolve string)."""
    if value is None:
        return {"nodes": [], "edges": []}
    if isinstance(value, dict):
        out = {
            "nodes": value.get("nodes") if isinstance(value.get("nodes"), list) else [],
            "edges": value.get("edges") if isinstance(value.get("edges"), list) else [],
        }
        return out
    if isinstance(value, str):
        try:
            data = json.loads(value)
            return normalize_flow_json(data)
        except Exception:
            return {"nodes": [], "edges": []}
    return {"nodes": [], "edges": []}


def flow_json_serializable(flow_json):
    """Garante que flow_json seja serializável em JSON (evita 500 no POST ao Supabase)."""
    try:
        return json.loads(json.dumps(flow_json, default=str))
    except Exception:
        return normalize_flow_json(flow_json)


def flow_validation_errors(flow_json) -> list[str]:
    """Retorna lista de erros se houver nós soltos (sem nenhuma conexão)."""
    flow_json = normalize_flow_json(flow_json) if not isinstance(flow_json, dict) else (flow_json or {})
    nodes = flow_json.get("nodes") or []
    edges = flow_json.get("edges") or []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return ["Estrutura do fluxo inválida."]
    node_ids = {n.get("id") for n in nodes if isinstance(n, dict) and n.get("id")}
    if not node_ids:
        return []
    connected = set()
    for e in edges:
        if isinstance(e, dict):
            connected.add(e.get("source"))
            connected.add(e.get("target"))
    soltos = node_ids - connected
    if soltos:
        return [f"Nó(s) sem conexão: {', '.join(sorted(soltos))}. Conecte todos os nós ao fluxo."]
    return []


# Canais/gatilhos disponíveis no Flow Builder (label para o menu)
FLOW_CHANNELS = [
    {"id": "default", "label": "Resposta padrão", "description": "Quando o assinante envia qualquer mensagem sem palavra-chave"},
    {"id": "welcome", "label": "Mensagem de boas-vindas", "description": "Primeira mensagem ao iniciar conversa"},
    {"id": "whatsapp", "label": "WhatsApp", "description": "Fluxo específico para WhatsApp"},
    {"id": "instagram", "label": "Instagram", "description": "Fluxo específico para Instagram Direct"},
    {"id": "messenger", "label": "Messenger", "description": "Fluxo específico para Facebook Messenger"},
    {"id": "website", "label": "Chat do site", "description": "Fluxo para o widget de chat no site"},
]
