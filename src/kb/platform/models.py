"""Platform-facing domain models for calendar/reminders access.

Pure data and pure Python — no PyObjC, no EventKit. These mirror EventKit's real
authorization states and event/reminder shapes closely enough to be a faithful
contract, but stay independent of any actual Apple framework call so ui/ can
develop against them before the real EventKit-backed service exists.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime


class AccessState(enum.Enum):
    """Mirrors EKAuthorizationStatus at the Python level."""

    NOT_DETERMINED = "not_determined"
    RESTRICTED = "restricted"
    DENIED = "denied"
    GRANTED = "granted"


class AccessDeniedError(Exception):
    """Raised when a service method is called without GRANTED access.

    Chosen over silently returning an empty list: "zero events today" and
    "you haven't granted calendar access" are different states, and the UI needs
    to render them differently (a clear "grant access" prompt vs. an empty
    dashboard). Collapsing both into an empty list would erase that distinction.
    """


@dataclass(frozen=True)
class CalendarEvent:
    title: str
    start: datetime
    end: datetime
    calendar_name: str
    notes: str | None = None


@dataclass(frozen=True)
class Reminder:
    title: str
    list_name: str
    due: datetime | None = None
    completed: bool = False
    notes: str | None = None
