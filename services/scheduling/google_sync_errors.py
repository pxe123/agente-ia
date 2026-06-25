"""Mensagens legíveis para erros de sync Google Calendar (Agenda IA → painel)."""
from __future__ import annotations

_AGENDA_ERROR_MESSAGES: dict[str, str] = {
    "GOOGLE_CREATE_FAILED": (
        "Não foi possível criar o evento no Google Calendar. "
        "Reconecte o Google do profissional em Agenda → Profissionais e tente de novo."
    ),
    "GOOGLE_NOT_CONNECTED_FOR_PROVIDER": (
        "O profissional desta marcação não tem Google Calendar ligado. "
        "Ligue o Google no cartão do profissional antes de confirmar."
    ),
    "agenda_confirm_falhou": "A confirmação falhou no motor Agenda IA.",
    "timeout": "Tempo esgotado ao contactar o Agenda IA.",
    "nao_pendente": "Este agendamento já não está pendente.",
    "nao_encontrado": "Agendamento não encontrado.",
}


def format_agenda_operation_error(code: str | None) -> str:
    raw = (code or "").strip()
    if not raw:
        return "erro desconhecido"
    if raw in _AGENDA_ERROR_MESSAGES:
        return _AGENDA_ERROR_MESSAGES[raw]
    if raw.startswith("http_"):
        return f"Erro de ligação ao Agenda IA ({raw})."
    return raw
