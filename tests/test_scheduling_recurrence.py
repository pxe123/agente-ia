"""Testes de regras e datas de recorrência."""
from __future__ import annotations

from datetime import date

import pytest

from services.scheduling.recurrence import (
    compute_occurrence_dates,
    normalize_rule,
    validate_recurrence_rule,
    format_series_summary,
)


class TestRecurrenceRules:
    def test_validate_weekly_requires_days(self):
        assert validate_recurrence_rule("weekly", {"days_of_week": []}) == "dias_semana_obrigatorios"
        assert validate_recurrence_rule("weekly", {"days_of_week": [0, 2]}) is None

    def test_validate_daily(self):
        assert validate_recurrence_rule("daily", {"mode": "weekdays"}) is None
        assert validate_recurrence_rule("invalid", {}) == "frequencia_invalida"

    def test_weekly_occurrences_mon_wed_fri(self):
        dates = compute_occurrence_dates(
            frequency="weekly",
            rule={"days_of_week": [0, 2, 4]},
            starts_on=date(2026, 6, 1),
            ends_on=date(2026, 6, 14),
            from_date=date(2026, 6, 1),
            to_date=date(2026, 6, 14),
        )
        # 1 Jun 2026 is Monday
        assert date(2026, 6, 1) in dates
        assert date(2026, 6, 3) in dates
        assert date(2026, 6, 5) in dates
        assert date(2026, 6, 2) not in dates

    def test_daily_weekdays_skips_weekend(self):
        dates = compute_occurrence_dates(
            frequency="daily",
            rule={"mode": "weekdays"},
            starts_on=date(2026, 6, 5),
            ends_on=date(2026, 6, 8),
            from_date=date(2026, 6, 5),
            to_date=date(2026, 6, 8),
        )
        assert date(2026, 6, 5) in dates  # Friday
        assert date(2026, 6, 6) not in dates  # Saturday
        assert date(2026, 6, 7) not in dates  # Sunday
        assert date(2026, 6, 8) in dates  # Monday

    def test_monthly_day_31_skips_february(self):
        dates = compute_occurrence_dates(
            frequency="monthly",
            rule={"day_of_month": 31},
            starts_on=date(2026, 1, 1),
            ends_on=date(2026, 3, 31),
            from_date=date(2026, 1, 1),
            to_date=date(2026, 3, 31),
        )
        assert date(2026, 1, 31) in dates
        assert date(2026, 2, 28) not in dates
        assert all(d.month != 2 for d in dates)

    def test_format_series_summary_weekly(self):
        series = {
            "frequency": "weekly",
            "rule": {"days_of_week": [0, 4]},
            "time_local": "10:00:00",
        }
        text = format_series_summary(series)
        assert "10:00" in text
        assert "Seg" in text
        assert "Sex" in text

    def test_normalize_rule_monthly_clamps(self):
        assert normalize_rule("monthly", {"day_of_month": 99})["day_of_month"] == 31


class TestRecurrenceNotify:
    def test_notify_skips_without_phone(self):
        from services.scheduling.recurrence import notify_recurrence_series_summary

        ok, err = notify_recurrence_series_summary("cid", {"contact_name": "Ana"})
        assert ok is False
        assert err

    def test_notify_sends_when_phone_present(self, monkeypatch):
        from database.models import SchedulingRecurrenceSeriesModel
        from services.scheduling.recurrence import notify_recurrence_series_summary

        sent = []

        def fake_send(cid, phone, text):
            sent.append((cid, phone, text))
            return True, None

        monkeypatch.setattr(
            "services.scheduling.confirmation_notify.send_scheduling_whatsapp_text",
            fake_send,
        )
        monkeypatch.setattr(
            "services.scheduling.recurrence.repository.get_settings",
            lambda _cid: {"timezone": "America/Sao_Paulo"},
        )
        series = {
            SchedulingRecurrenceSeriesModel.CONTACT_PHONE: "14999999999",
            SchedulingRecurrenceSeriesModel.CONTACT_NAME: "Maria",
            SchedulingRecurrenceSeriesModel.FREQUENCY: "weekly",
            SchedulingRecurrenceSeriesModel.RULE: {"days_of_week": [0]},
            SchedulingRecurrenceSeriesModel.TIME_LOCAL: "10:00:00",
            SchedulingRecurrenceSeriesModel.STARTS_ON: "2026-06-01",
        }
        ok, err = notify_recurrence_series_summary("cid", series)
        assert ok is True
        assert err is None
        assert sent and "Maria" in sent[0][2]
