"""Service interfaces for macOS Calendar/Reminders access.

Defined as typing.Protocol rather than ABC: these are swappable backends (a
FakeCalendarService for tests/ui-development now, an EventKit-backed service
later) that are never instantiated through a shared base class or given
inherited behavior. Protocol gives structural typing — the EventKit-backed
implementation in a future task doesn't need to know this module exists, it
just needs to match the shape. ABC would buy us nothing here since there's no
shared implementation to factor upward.

Every method that reads or writes calendar/reminders data raises
AccessDeniedError when access_state() is not GRANTED, rather than returning an
empty list — see AccessDeniedError's docstring in models.py for why.
"""

from __future__ import annotations

from typing import Protocol

from kb.platform.models import AccessState, CalendarEvent, Reminder


class CalendarService(Protocol):
    def access_state(self) -> AccessState:
        """Current permission status. No side effects, never prompts."""
        ...

    def request_access(self) -> AccessState:
        """Trigger (or simulate) the OS permission prompt; return the resulting state."""
        ...

    def upcoming_events(self, within_days: int) -> list[CalendarEvent]:
        """Events starting within the next `within_days` days.

        Raises AccessDeniedError if access_state() is not GRANTED.
        """
        ...


class RemindersService(Protocol):
    def access_state(self) -> AccessState:
        """Current permission status. No side effects, never prompts."""
        ...

    def request_access(self) -> AccessState:
        """Trigger (or simulate) the OS permission prompt; return the resulting state."""
        ...

    def open_reminders(self) -> list[Reminder]:
        """Incomplete reminders across all lists.

        Raises AccessDeniedError if access_state() is not GRANTED.
        """
        ...

    def complete_reminder(self, reminder: Reminder) -> None:
        """Mark a reminder complete (Phase 2 write-back).

        Raises AccessDeniedError if access_state() is not GRANTED.
        """
        ...
