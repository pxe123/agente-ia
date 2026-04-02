"""
Helpers para variáveis comuns em render_template (evita esquecer embed_key, etc.).
"""


def with_embed_template_kwargs(**kwargs):
    """
    Se kwargs contém cliente (dict) com embed_key, repassa embed_key ao template.
    Não sobrescreve embed_key já passado explicitamente.
    Não define embed_key quando ausente (o context_processor global em app.py preenche para sessão autenticada).
    """
    out = dict(kwargs)
    if "embed_key" in out:
        return out
    cliente = out.get("cliente")
    if isinstance(cliente, dict):
        v = (cliente.get("embed_key") or cliente.get("website_chat_embed_key") or "").strip()
        if v:
            out["embed_key"] = v
    return out
