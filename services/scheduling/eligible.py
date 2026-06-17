"""Profissionais elegíveis para um serviço (fonte única)."""
from __future__ import annotations


def eligible_professionals(
    services: list[dict],
    professionals: list[dict],
    service_id: str,
) -> list[dict]:
    svc = next((x for x in services if str(x.get("id")) == str(service_id)), None)
    if not svc:
        return []
    pid = svc.get("professional_id")
    active = [p for p in professionals if p.get("active", True) is not False and p.get("id")]
    if pid:
        return [p for p in active if str(p.get("id")) == str(pid)]
    return list(active)
