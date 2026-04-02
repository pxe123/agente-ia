"""
Remoção de identificadores de tenant enviados pelo cliente.
O backend deve usar sempre get_current_cliente_id (sessão) ou validação forte (ex.: embed_key).
"""

_UNTRUSTED_TENANT_KEYS = frozenset(
    {
        "cliente_id",
        "clienteId",
        "CLIENTE_ID",
        "tenant_id",
        "tenantId",
        "TENANT_ID",
    }
)


def strip_untrusted_tenant_ids(data):
    """
    Copia um dict ou objeto tipo MultiDict e remove chaves de tenant que não devem vir do front.
    """
    if data is None:
        return {}
    if not hasattr(data, "items"):
        return {}
    return {k: v for k, v in data.items() if k not in _UNTRUSTED_TENANT_KEYS}
