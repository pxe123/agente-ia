"""Testes dos adaptadores de motor."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from services.scheduling.motor_adapters.base import BookOccurrenceRequest
from services.scheduling.motor_adapters.factory import get_motor_adapter
from services.scheduling.motor_adapters.internal import InternalMotorAdapter


class TestMotorAdapters:
    @patch("services.scheduling.motor_adapters.factory.scheduling_uses_internal_motor", return_value=True)
    def test_factory_internal(self, _m):
        assert isinstance(get_motor_adapter("cid"), InternalMotorAdapter)

    @patch("services.scheduling.motor_adapters.factory.scheduling_uses_internal_motor", return_value=False)
    def test_factory_external(self, _m):
        from services.scheduling.motor_adapters.agenda_ia import AgendaIAMotorAdapter

        assert isinstance(get_motor_adapter("cid"), AgendaIAMotorAdapter)

    @patch("services.scheduling.motor_adapters.internal.book_appointment")
    @patch("services.scheduling.motor_adapters.internal.check_slot_free_local", return_value=True)
    def test_internal_single_booking(self, _free, mock_book):
        mock_book.return_value = ({"id": "a1"}, None)
        adapter = InternalMotorAdapter()
        starts = datetime(2026, 6, 16, 10, 0, tzinfo=timezone.utc)
        result = adapter.book_occurrence(
            BookOccurrenceRequest(
                cliente_id="c1",
                service_id="s1",
                professional_id="p1",
                starts_at=starts,
                ends_at=starts + timedelta(minutes=30),
                contact_name="João",
            )
        )
        assert result.row is not None
        assert result.error is None
        mock_book.assert_called_once()

    @patch("services.scheduling.motor_adapters.agenda_ia.repository")
    @patch("services.scheduling.motor_adapters.agenda_ia.create_appointment_in_agendamento_ia")
    @patch("services.scheduling.motor_adapters.agenda_ia.recurrence_external_sync_enabled", return_value=True)
    @patch("services.scheduling.motor_adapters.agenda_ia.check_slot_free_local", return_value=True)
    @patch("services.scheduling.motor_adapters.agenda_ia.revalidate_overlap_after_insert", return_value=True)
    def test_external_synced(self, _rev, _free, _sync_en, mock_create, mock_repo):
        from services.scheduling.motor_adapters.agenda_ia import AgendaIAMotorAdapter

        mock_create.return_value = ("ext-1", None)
        mock_repo.insert_appointment.return_value = {"id": "local-1", "meta": {}}
        mock_repo.get_appointment.return_value = {"id": "local-1", "meta": {"motor_sync": "synced"}}

        adapter = AgendaIAMotorAdapter()
        starts = datetime(2026, 6, 16, 10, 0, tzinfo=timezone.utc)
        result = adapter.book_occurrence(
            BookOccurrenceRequest(
                cliente_id="c1",
                service_id="s1",
                professional_id="p1",
                starts_at=starts,
                ends_at=starts + timedelta(minutes=30),
                contact_name="João",
                recurrence_series_id="series-1",
                series_occurrence_at=starts,
            )
        )
        assert result.row is not None
        assert result.motor_sync == "synced"
        mock_repo.set_appointment_external_id.assert_called_once()
