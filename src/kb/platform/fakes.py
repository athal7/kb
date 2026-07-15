"""In-memory fakes for CalendarService/RemindersService.

Real test doubles for use in tests now and ui/ development later — constructed
with canned data and a settable AccessState, not throwaway stubs.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

from kb.platform.models import AccessDeniedError, AccessState, CalendarEvent, Reminder


class FakeCalendarService:
    """Returns canned events when granted; ignores `within_days` (no real dates to filter)."""

    def __init__(
        self,
        events: Sequence[CalendarEvent] | None = None,
        access_state: AccessState = AccessState.GRANTED,
        access_state_after_request: AccessState | None = None,
    ) -> None:
        self._events = list(events) if events else []
        self._access_state = access_state
        self._access_state_after_request = access_state_after_request

    def access_state(self) -> AccessState:
        return self._access_state

    def request_access(self) -> AccessState:
        if self._access_state_after_request is not None:
            self._access_state = self._access_state_after_request
        return self._access_state

    def upcoming_events(self, within_days: int) -> list[CalendarEvent]:
        if self._access_state is not AccessState.GRANTED:
            raise AccessDeniedError("Calendar access is not granted")
        return list(self._events)


class FakeRemindersService:
    """Returns canned incomplete reminders when granted.

    complete_reminder() mutates the fake's internal store in place.
    """

    def __init__(
        self,
        reminders: Sequence[Reminder] | None = None,
        access_state: AccessState = AccessState.GRANTED,
        access_state_after_request: AccessState | None = None,
    ) -> None:
        self._reminders = list(reminders) if reminders else []
        self._access_state = access_state
        self._access_state_after_request = access_state_after_request

    def access_state(self) -> AccessState:
        return self._access_state

    def request_access(self) -> AccessState:
        if self._access_state_after_request is not None:
            self._access_state = self._access_state_after_request
        return self._access_state

    def open_reminders(self) -> list[Reminder]:
        self._require_granted()
        return [r for r in self._reminders if not r.completed]

    def complete_reminder(self, reminder: Reminder) -> None:
        self._require_granted()
        for index, existing in enumerate(self._reminders):
            if existing == reminder:
                self._reminders[index] = dataclasses.replace(existing, completed=True)
                return
        raise ValueError(f"Reminder not found in fake store: {reminder.title!r}")

    def _require_granted(self) -> None:
        if self._access_state is not AccessState.GRANTED:
            raise AccessDeniedError("Reminders access is not granted")
