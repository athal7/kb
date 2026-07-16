"""EventKit-backed CalendarService and RemindersService implementations.

This is the one module in platform/ that legitimately imports EventKit/objc —
see test_platform_boundary.py's PURE_PYTHON_MODULES allowlist, which
deliberately excludes this file so a reviewer has to consciously exempt it
rather than have it silently pass.

Reads are implemented; complete_reminder() is Phase 2 write-back and raises
NotImplementedError (see interfaces.py's docstring on that method).

Events fetch synchronously (EKEventStore.eventsMatchingPredicate_). Reminders
and permission requests are async-only in EventKit, calling back on an
arbitrary GCD queue rather than a run loop — both are bridged to synchronous
Python calls with a plain threading.Event, the pattern EventKit consumers
outside AppKit's run loop use in practice.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

try:
    import EventKit
except ImportError:
    class DummyEventKit:
        EKAuthorizationStatusNotDetermined = 0
        EKAuthorizationStatusRestricted = 1
        EKAuthorizationStatusDenied = 2
        EKAuthorizationStatusFullAccess = 3
        EKEntityTypeEvent = 0
        EKEntityTypeReminder = 1
        class EKEventStore:
            @classmethod
            def alloc(cls):
                return cls()
            def init(self):
                return self
    EventKit = DummyEventKit  # type: ignore

from kb.platform.models import AccessDeniedError, AccessState, CalendarEvent, Reminder

_FETCH_TIMEOUT_SECONDS = 10

# EKAuthorizationStatusWriteOnly and any future status EventKit adds aren't in
# this map and fall through to DENIED in _map_authorization_status — a status
# that isn't known to grant full read access shouldn't be treated as GRANTED.
_AUTHORIZATION_STATUS_TO_ACCESS_STATE = {
    EventKit.EKAuthorizationStatusNotDetermined: AccessState.NOT_DETERMINED,
    EventKit.EKAuthorizationStatusRestricted: AccessState.RESTRICTED,
    EventKit.EKAuthorizationStatusDenied: AccessState.DENIED,
    EventKit.EKAuthorizationStatusFullAccess: AccessState.GRANTED,
}


def _map_authorization_status(raw_status: int) -> AccessState:
    """Map a raw EKAuthorizationStatus int to AccessState."""
    return _AUTHORIZATION_STATUS_TO_ACCESS_STATE.get(raw_status, AccessState.DENIED)


def _datetime_from_nsdate(ns_date) -> datetime | None:
    """Convert an NSDate to a local-time datetime, or None if ns_date is None."""
    if ns_date is None:
        return None
    return datetime.fromtimestamp(ns_date.timeIntervalSince1970())


def _datetime_from_components(components) -> datetime | None:
    """Convert an NSDateComponents (EKReminder.dueDateComponents()) to a datetime.

    Returns None if components is None or its date portion (year/month/day) is
    unset — EventKit represents "no value" with NSDateComponentUndefined
    rather than nil fields. Missing time-of-day components (hour/minute/second)
    default to midnight, which is how EventKit represents all-day due dates.
    """
    if components is None:
        return None
    undefined = 9223372036854775807  # NSDateComponentUndefined
    year, month, day = components.year(), components.month(), components.day()
    if undefined in (year, month, day):
        return None
    hour = components.hour()
    minute = components.minute()
    second = components.second()
    return datetime(
        year,
        month,
        day,
        0 if hour == undefined else hour,
        0 if minute == undefined else minute,
        0 if second == undefined else second,
    )


class EventKitCalendarService:
    def __init__(self, store: EventKit.EKEventStore | None = None) -> None:
        self._store = store

    @property
    def _event_store(self) -> EventKit.EKEventStore:
        if self._store is None:
            self._store = EventKit.EKEventStore.alloc().init()
        return self._store

    def access_state(self) -> AccessState:
        raw_status = EventKit.EKEventStore.authorizationStatusForEntityType_(
            EventKit.EKEntityTypeEvent
        )
        return _map_authorization_status(raw_status)

    def request_access(self) -> AccessState:
        done = threading.Event()

        def handler(granted, error):
            done.set()

        self._event_store.requestFullAccessToEventsWithCompletion_(handler)
        done.wait(timeout=_FETCH_TIMEOUT_SECONDS)
        time.sleep(0.05)  # see ronaldoussoren/pyobjc#609
        return self.access_state()

    def upcoming_events(self, within_days: int) -> list[CalendarEvent]:
        if self.access_state() is not AccessState.GRANTED:
            raise AccessDeniedError("Calendar access is not granted")

        store = self._event_store
        start = datetime.now()
        end = start + timedelta(days=within_days)
        calendars = store.calendarsForEntityType_(EventKit.EKEntityTypeEvent)
        predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
            start, end, calendars
        )
        events = store.eventsMatchingPredicate_(predicate)
        return [self._to_calendar_event(event) for event in events]

    @staticmethod
    def _to_calendar_event(event) -> CalendarEvent:
        return CalendarEvent(
            title=event.title() or "",
            start=_datetime_from_nsdate(event.startDate()),
            end=_datetime_from_nsdate(event.endDate()),
            calendar_name=event.calendar().title() or "",
            notes=event.notes() or None,
        )


class EventKitRemindersService:
    def __init__(self, store: EventKit.EKEventStore | None = None) -> None:
        self._store = store

    @property
    def _event_store(self) -> EventKit.EKEventStore:
        if self._store is None:
            self._store = EventKit.EKEventStore.alloc().init()
        return self._store

    def access_state(self) -> AccessState:
        raw_status = EventKit.EKEventStore.authorizationStatusForEntityType_(
            EventKit.EKEntityTypeReminder
        )
        return _map_authorization_status(raw_status)

    def request_access(self) -> AccessState:
        done = threading.Event()

        def handler(granted, error):
            done.set()

        self._event_store.requestFullAccessToRemindersWithCompletion_(handler)
        done.wait(timeout=_FETCH_TIMEOUT_SECONDS)
        time.sleep(0.05)  # see ronaldoussoren/pyobjc#609
        return self.access_state()

    def open_reminders(self) -> list[Reminder]:
        if self.access_state() is not AccessState.GRANTED:
            raise AccessDeniedError("Reminders access is not granted")

        store = self._event_store
        lists = store.calendarsForEntityType_(EventKit.EKEntityTypeReminder)
        predicate = store.predicateForRemindersInCalendars_(lists)

        done = threading.Event()
        results: list = []

        def handler(reminders):
            results.extend(reminders or [])
            done.set()

        store.fetchRemindersMatchingPredicate_completion_(predicate, handler)
        done.wait(timeout=_FETCH_TIMEOUT_SECONDS)
        time.sleep(0.05)  # see ronaldoussoren/pyobjc#609

        return [self._to_reminder(reminder) for reminder in results if not reminder.isCompleted()]

    def complete_reminder(self, reminder: Reminder) -> None:
        raise NotImplementedError(
            "Reminders write-back (complete_reminder) is Phase 2 — not implemented yet"
        )

    @staticmethod
    def _to_reminder(reminder) -> Reminder:
        return Reminder(
            title=reminder.title() or "",
            list_name=reminder.calendar().title() or "",
            due=_datetime_from_components(reminder.dueDateComponents()),
            completed=reminder.isCompleted(),
            notes=reminder.notes() or None,
        )
