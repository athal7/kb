"""In-memory fakes for CalendarService/RemindersService.

These are the test doubles ui/ will import once dashboard work starts, so their
behavior is specified here rather than treated as throwaway stubs: canned data
flows through when access is granted, AccessDeniedError surfaces a clear signal
when it isn't (never an empty list masquerading as "no events today"), and
request_access() simulates the EventKit permission dialog transitioning state.
"""

from datetime import datetime, timedelta

import pytest

from kb.platform.fakes import FakeCalendarService, FakeRemindersService
from kb.platform.models import AccessDeniedError, AccessState, CalendarEvent, Reminder

NOT_GRANTED_STATES = [AccessState.DENIED, AccessState.NOT_DETERMINED, AccessState.RESTRICTED]


def _event(title="Standup", days_from_now=1):
    start = datetime(2026, 7, 14, 9, 0) + timedelta(days=days_from_now)
    return CalendarEvent(
        title=title,
        start=start,
        end=start + timedelta(minutes=30),
        calendar_name="Work",
    )


def _reminder(title="Ship the thing", completed=False):
    return Reminder(title=title, list_name="Inbox", completed=completed)


class DescribeFakeCalendarService:
    def it_returns_canned_events_when_access_is_granted(self):
        events = [_event("Standup"), _event("1:1")]
        service = FakeCalendarService(events=events, access_state=AccessState.GRANTED)

        assert service.upcoming_events(within_days=7) == events

    @pytest.mark.parametrize("state", NOT_GRANTED_STATES)
    def it_raises_access_denied_when_access_is_not_granted(self, state):
        service = FakeCalendarService(events=[_event()], access_state=state)

        with pytest.raises(AccessDeniedError):
            service.upcoming_events(within_days=7)

    def it_reports_the_configured_access_state(self):
        service = FakeCalendarService(access_state=AccessState.NOT_DETERMINED)

        assert service.access_state() == AccessState.NOT_DETERMINED

    def it_transitions_access_state_when_request_access_is_configured_to_grant(self):
        service = FakeCalendarService(
            access_state=AccessState.NOT_DETERMINED,
            access_state_after_request=AccessState.GRANTED,
        )

        result = service.request_access()

        assert result == AccessState.GRANTED
        assert service.access_state() == AccessState.GRANTED

    def it_leaves_access_state_unchanged_when_request_access_has_no_configured_transition(self):
        service = FakeCalendarService(access_state=AccessState.RESTRICTED)

        result = service.request_access()

        assert result == AccessState.RESTRICTED
        assert service.access_state() == AccessState.RESTRICTED


class DescribeFakeRemindersService:
    def it_returns_only_incomplete_reminders_when_access_is_granted(self):
        open_reminder = _reminder("Ship the thing", completed=False)
        done_reminder = _reminder("Already done", completed=True)
        service = FakeRemindersService(
            reminders=[open_reminder, done_reminder], access_state=AccessState.GRANTED
        )

        assert service.open_reminders() == [open_reminder]

    @pytest.mark.parametrize("state", NOT_GRANTED_STATES)
    def it_raises_access_denied_when_access_is_not_granted(self, state):
        service = FakeRemindersService(reminders=[_reminder()], access_state=state)

        with pytest.raises(AccessDeniedError):
            service.open_reminders()

    def it_removes_a_completed_reminder_from_open_reminders(self):
        reminder = _reminder("Ship the thing")
        service = FakeRemindersService(reminders=[reminder], access_state=AccessState.GRANTED)

        service.complete_reminder(reminder)

        assert service.open_reminders() == []

    @pytest.mark.parametrize("state", NOT_GRANTED_STATES)
    def it_raises_access_denied_on_complete_reminder_when_access_is_not_granted(self, state):
        reminder = _reminder("Ship the thing")
        service = FakeRemindersService(reminders=[reminder], access_state=state)

        with pytest.raises(AccessDeniedError):
            service.complete_reminder(reminder)

    def it_transitions_access_state_when_request_access_is_configured_to_grant(self):
        service = FakeRemindersService(
            access_state=AccessState.NOT_DETERMINED,
            access_state_after_request=AccessState.GRANTED,
        )

        result = service.request_access()

        assert result == AccessState.GRANTED
        assert service.access_state() == AccessState.GRANTED
