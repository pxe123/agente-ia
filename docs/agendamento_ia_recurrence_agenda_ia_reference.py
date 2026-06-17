"""
Referência de implementação para o repositório agendamento-ia.

Copiar/adaptar para:
  app/routes/integrations_zapaction.py
  app/services/zapaction_panel_booking.py

Contrato: docs/agendamento_ia_recurrence_contract.md (repo agente-ia)
"""
from __future__ import annotations

# --- FastAPI route sketch (agendamento-ia) ---

"""
@router.post("/v1/integrations/zapaction/appointments")
async def zapaction_create_appointment(body: ZapactionAppointmentCreate):
    # 1. Validar request_schema_version == 1
    # 2. Idempotência: (cliente_id, zapaction_appointment_id) -> retornar appointment_id existente
    # 3. Validar service_id / provider_id no tenant
    # 4. Verificar slot livre (mesma lógica do booking_core)
    # 5. Criar AppointmentRow com metadata incluindo recurrence.series_id se presente
    # 6. Emitir webhook appointment.created com zapaction_appointment_id + recurrence.*
    # 7. Retornar { appointment_id, status }


@router.post("/v1/integrations/zapaction/appointments/cancel-batch")
async def zapaction_cancel_batch(body: ZapactionAppointmentCancelBatch):
    # scope following: cancel where series_id match AND starts_at >= from_starts_at
    # scope all: cancel all for series_id in metadata
    # scope ids: cancel listed appointment_ids
    # Emitir appointment.cancelled por cada uma
    # Retornar { cancelled, appointment_ids }
"""

# Campos a persistir no AppointmentRow.metadata (Agenda IA):
#   zapaction_appointment_id
#   recurrence: { series_id, occurrence_at, is_exception }
#   source: panel | panel_recurrence
