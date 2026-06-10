"""
Job: lembretes WhatsApp antes das marcações (P2).

Cron sugerido (a cada 15 min):
  python scripts/run_scheduling_reminders.py
"""
from __future__ import annotations

from typing import Any

from services.scheduling.reminders import run_appointment_reminders


def run_scheduling_reminders(limit: int = 200) -> dict[str, Any]:
    return run_appointment_reminders(limit=limit)
