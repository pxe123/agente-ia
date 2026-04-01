# services/sent_message_cache.py
"""
Cache de mensagens enviadas por nós (ex.: resposta da IA via WAHA).
Usado pelo webhook WAHA para não registrar de novo quando o WAHA devolve
o evento message.any com fromMe=true (eco da nossa própria mensagem).
"""
import time
from collections import OrderedDict

# (cliente_id, remote_id_normalized, content_normalized) -> timestamp
_sent_cache = OrderedDict()
_TTL_SEC = 90
_MAX_ENTRIES = 500


def _normalizar_remote_id(remote_id: str) -> str:
    """Canonicaliza para @c.us e @s.whatsapp.net baterem (evita duplicata do eco no chat)."""
    s = (remote_id or "").strip()
    if "@" in s:
        s = s.split("@")[0].strip()
    return s


def _key(cliente_id, remote_id, content):
    c = (content or "").strip()[:500]
    return (str(cliente_id), _normalizar_remote_id(remote_id), c)


def registrar_envio(cliente_id, remote_id, content):
    """Chamar quando enviamos uma mensagem pelo WhatsApp (ex.: resposta da IA)."""
    k = _key(cliente_id, remote_id, content)
    _sent_cache[k] = time.time()
    while len(_sent_cache) > _MAX_ENTRIES:
        _sent_cache.popitem(last=False)


def foi_envio_recente(cliente_id, remote_id, content):
    """
    True se esta combinação foi enviada por nós nos últimos _TTL_SEC segundos.
    Usado no webhook para ignorar o eco (fromMe=true) da nossa própria mensagem.
    """
    k = _key(cliente_id, remote_id, content)
    now = time.time()
    # Limpar entradas expiradas ao checar
    to_del = [key for key, ts in _sent_cache.items() if now - ts > _TTL_SEC]
    for key in to_del:
        _sent_cache.pop(key, None)
    if k not in _sent_cache:
        return False
    if now - _sent_cache[k] > _TTL_SEC:
        _sent_cache.pop(k, None)
        return False
    # Encontrado e dentro do TTL: é eco, remover para não bloquear próxima vez que enviarmos o mesmo texto
    _sent_cache.pop(k, None)
    return True
