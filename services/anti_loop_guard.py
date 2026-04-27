"""
Guardião anti-loop (in-memory) para impedir rajadas de envio por conversa.

Motivação: em cenários de eco/duplicidade de webhook ou entradas inesperadas, o bot pode entrar
em loop e disparar muitas mensagens em sequência. Este módulo aplica um "circuit breaker"
por (cliente_id, canal, remote_id) para bloquear envios por alguns minutos.

Observação: in-memory => por processo. Em múltiplas réplicas, o bloqueio é por instância.
Ainda assim reduz drasticamente impacto e evita travar contas por flood.
"""

from __future__ import annotations

import time
from collections import OrderedDict


class AntiLoopGuard:
    # Se exceder MAX_OUTGOING em WINDOW_SEC, bloqueia por BLOCK_SEC.
    WINDOW_SEC = 20
    MAX_OUTGOING = 6
    BLOCK_SEC = 180  # 3 min

    # Limites do cache in-memory
    _MAX_KEYS = 5000

    # key -> list[timestamps]
    _outgoing_ts: OrderedDict[tuple[str, str, str], list[float]] = OrderedDict()
    # key -> block_until_ts
    _blocked_until: OrderedDict[tuple[str, str, str], float] = OrderedDict()

    @staticmethod
    def _key(cliente_id: str | None, canal: str | None, remote_id: str | None) -> tuple[str, str, str]:
        cid = (str(cliente_id) if cliente_id is not None else "").strip()
        c = (str(canal) if canal is not None else "").strip().lower()
        rid = (str(remote_id) if remote_id is not None else "").strip()
        # Normaliza JID do WAHA para reduzir chaves duplicadas
        if "@" in rid:
            rid = rid.split("@", 1)[0].strip()
        return (cid, c, rid)

    @classmethod
    def _gc(cls, now: float) -> None:
        # Remove bloqueios expirados
        expired_blocks = [k for k, until in cls._blocked_until.items() if until <= now]
        for k in expired_blocks:
            cls._blocked_until.pop(k, None)

        # Remove timestamps antigos
        window_start = now - float(cls.WINDOW_SEC)
        to_del = []
        for k, lst in cls._outgoing_ts.items():
            if not lst:
                to_del.append(k)
                continue
            # Filtra in-place
            new_lst = [t for t in lst if t >= window_start]
            if new_lst:
                cls._outgoing_ts[k] = new_lst
            else:
                to_del.append(k)
        for k in to_del:
            cls._outgoing_ts.pop(k, None)

        # Limita tamanho (LRU-ish via OrderedDict)
        while len(cls._outgoing_ts) > cls._MAX_KEYS:
            cls._outgoing_ts.popitem(last=False)
        while len(cls._blocked_until) > cls._MAX_KEYS:
            cls._blocked_until.popitem(last=False)

    @classmethod
    def is_blocked(cls, cliente_id: str | None, canal: str | None, remote_id: str | None) -> tuple[bool, float]:
        """
        Retorna (blocked, seconds_remaining).
        """
        now = time.time()
        cls._gc(now)
        k = cls._key(cliente_id, canal, remote_id)
        until = float(cls._blocked_until.get(k) or 0.0)
        if until > now:
            return True, max(0.0, until - now)
        return False, 0.0

    @classmethod
    def record_outgoing(cls, cliente_id: str | None, canal: str | None, remote_id: str | None) -> None:
        """
        Registra uma tentativa/ocorrência de envio de mensagem pelo bot para esta conversa.
        Se exceder o limite, ativa o bloqueio temporário.
        """
        now = time.time()
        cls._gc(now)
        k = cls._key(cliente_id, canal, remote_id)

        # Atualiza LRU
        if k in cls._outgoing_ts:
            cls._outgoing_ts.move_to_end(k)
        if k in cls._blocked_until:
            cls._blocked_until.move_to_end(k)

        lst = cls._outgoing_ts.get(k) or []
        lst.append(now)
        # Filtra janela
        window_start = now - float(cls.WINDOW_SEC)
        lst = [t for t in lst if t >= window_start]
        cls._outgoing_ts[k] = lst

        if len(lst) > int(cls.MAX_OUTGOING):
            cls._blocked_until[k] = now + float(cls.BLOCK_SEC)

