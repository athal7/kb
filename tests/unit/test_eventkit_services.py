"""Tests for the EventKit-backed CalendarService/RemindersService.

Anything that touches a real EKEventStore (permission checks, fetches) needs
live TCC state and is gated behind @pytest.mark.manual — see the module
docstring in eventkit_services.py. What's left, and what's covered here, is
the pure conversion logic: mapping raw EKAuthorizationStatus ints to
AccessState, and converting EventKit's date representations (NSDate,
NSDateComponents) to plain datetimes. Both are exercised with plain ints and
duck-typed fakes, no framework calls involved.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from kb.platform.eventkit_services import (
    EventKitCalendarService,
    EventKitRemindersService,
    _datetime_from_components,
    _datetime_from_nsdate,
    _map_authorization_status,
)
from kb.platform.models import AccessState, Reminder


class _FakeDateComponents:
    """Duck-types NSDateComponents' accessor methods for unit testing."""

    _UNDEFINED = 9223372036854775807

    def __init__(self, year=None, month=None, day=None, hour=None, minute=None, second=None):
        self._values = {
            "year": self._UNDEFINED if year is None else year,
            "month": self._UNDEFINED if month is None else month,
            "day": self._UNDEFINED if day is None else day,
            "hour": self._UNDEFINED if hour is None else hour,
            "minute": self._UNDEFINED if minute is None else minute,
            "second": self._UNDEFINED if second is None else second,
        }

    def year(self):
        return self._values["year"]

    def month(self):
        return self._values["month"]

    def day(self):
        return self._values["day"]

    def hour(self):
        return self._values["hour"]

    def minute(self):
        return self._values["minute"]

    def second(self):
        return self._values["second"]


class _FakeNSDate:
    """Duck-types NSDate's timeIntervalSince1970 for unit testing."""

    def __init__(self, timestamp: float):
        self._timestamp = timestamp

    def timeIntervalSince1970(self):
        return self._timestamp


class DescribeMapAuthorizationStatus:
    def it_maps_not_determined(self):
        assert _map_authorization_status(0) == AccessState.NOT_DETERMINED

    def it_maps_restricted(self):
        assert _map_authorization_status(1) == AccessState.RESTRICTED

    def it_maps_denied(self):
        assert _map_authorization_status(2) == AccessState.DENIED

    def it_maps_full_access_to_granted(self):
        assert _map_authorization_status(3) == AccessState.GRANTED

    def it_treats_unknown_statuses_as_denied(self):
        # e.g. EKAuthorizationStatusWriteOnly (4) — write-only reminders access
        # can't satisfy a read-oriented service, so don't call it GRANTED.
        assert _map_authorization_status(4) == AccessState.DENIED


class DescribeDatetimeFromNsdate:
    def it_returns_none_for_none(self):
        assert _datetime_from_nsdate(None) is None

    def it_converts_a_timestamp_to_a_local_datetime(self):
        ns_date = _FakeNSDate(0.0)

        result = _datetime_from_nsdate(ns_date)

        assert result == datetime.fromtimestamp(0.0)


class DescribeDatetimeFromComponents:
    def it_returns_none_for_none(self):
        assert _datetime_from_components(None) is None

    def it_returns_none_when_the_date_portion_is_undefined(self):
        components = _FakeDateComponents()

        assert _datetime_from_components(components) is None

    def it_builds_a_datetime_from_full_components(self):
        components = _FakeDateComponents(
            year=2026, month=7, day=14, hour=9, minute=30, second=0
        )

        result = _datetime_from_components(components)

        assert result == datetime(2026, 7, 14, 9, 30, 0)

    def it_defaults_missing_time_components_to_midnight(self):
        components = _FakeDateComponents(year=2026, month=7, day=14)

        result = _datetime_from_components(components)

        assert result == datetime(2026, 7, 14, 0, 0, 0)


class DescribeEventKitRemindersServiceCompleteReminder:
    def it_raises_not_implemented_since_writes_are_phase_2(self):
        service = EventKitRemindersService()
        reminder = Reminder(title="Ship the thing", list_name="Inbox")

        with pytest.raises(NotImplementedError):
            service.complete_reminder(reminder)


@pytest.mark.manual
class DescribeEventKitCalendarServiceLive:
    """Requires a real EKEventStore and live TCC state. Run manually."""

    def it_reports_the_real_access_state(self):
        service = EventKitCalendarService()

        assert service.access_state() in AccessState

    def it_prompts_for_access_and_returns_the_resulting_state(self):
        service = EventKitCalendarService()

        result = service.request_access()

        assert result in AccessState

    def it_returns_upcoming_events_when_access_is_granted(self):
        service = EventKitCalendarService()
        if service.access_state() is not AccessState.GRANTED:
            pytest.skip("Calendar access not granted on this machine")

        events = service.upcoming_events(within_days=7)

        assert isinstance(events, list)


@pytest.mark.manual
class DescribeEventKitRemindersServiceLive:
    """Requires a real EKEventStore and live TCC state. Run manually."""

    def it_reports_the_real_access_state(self):
        service = EventKitRemindersService()

        assert service.access_state() in AccessState

    def it_prompts_for_access_and_returns_the_resulting_state(self):
        service = EventKitRemindersService()

        result = service.request_access()

        assert result in AccessState

    def it_returns_open_reminders_when_access_is_granted(self):
        service = EventKitRemindersService()
        if service.access_state() is not AccessState.GRANTED:
            pytest.skip("Reminders access not granted on this machine")

        reminders = service.open_reminders()

        assert isinstance(reminders, list)
