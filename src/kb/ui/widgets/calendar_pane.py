"""Upcoming-events pane, backed by any CalendarService implementation.

Only ever talks to the service through the CalendarService Protocol — never
imports EventKit/objc directly, so swapping FakeCalendarService for a real
EventKit-backed service later is a construction-site change in __main__.py, not
a UI rewrite.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Label

from kb.platform.interfaces import CalendarService
from kb.ui.widgets.access_gated_pane import AccessGatedPane

DEFAULT_WITHIN_DAYS = 7


class CalendarPane(AccessGatedPane):
    """Upcoming events, or an explicit access-state message.

    "Zero events" and "you haven't granted calendar access" are different
    states and must render differently — an empty pane would erase that
    distinction (see AccessDeniedError's docstring in platform/models.py).
    """

    BORDER_TITLE = "Upcoming Events"
    resource_name = "Calendar"

    def __init__(
        self,
        service: CalendarService,
        *,
        within_days: int = DEFAULT_WITHIN_DAYS,
        id: str | None = None,
    ) -> None:
        super().__init__(service, id=id)
        self._within_days = within_days

    def _fetch_content(self) -> list:
        return sorted(
            self._service.upcoming_events(within_days=self._within_days),
            key=lambda event: event.start,
        )

    def _render_granted_content(self, content: list) -> ComposeResult:
        events = content
        if not events:
            yield Label("No upcoming events.", classes="empty-state", markup=False)
            return

        for event in events:
            yield Label(
                f"{event.start:%b %d %H:%M} — {event.title}",
                classes="calendar-event",
                markup=False,
            )
