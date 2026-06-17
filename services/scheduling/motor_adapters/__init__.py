"""Adaptadores de materialização de marcações por motor de agenda."""
from __future__ import annotations

from services.scheduling.motor_adapters.base import (
    BatchCancelResult,
    BookOccurrenceRequest,
    BookOccurrenceResult,
    MotorAdapter,
)
from services.scheduling.motor_adapters.factory import get_motor_adapter

__all__ = [
    "BatchCancelResult",
    "BookOccurrenceRequest",
    "BookOccurrenceResult",
    "MotorAdapter",
    "get_motor_adapter",
]
