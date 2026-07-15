"""Open-reminders pane, backed by any RemindersService implementation.

Mirrors CalendarPane's access-state handling: only ever talks to the service
through the RemindersService Protocol, never EventKit/objc directly.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Label

from kb.platform.interfaces import RemindersService
from kb.ui.widgets.access_gated_pane import AccessGatedPane


class RemindersPane(AccessGatedPane):
    """Open reminders, or an explicit access-state message."""

    BORDER_TITLE = "Reminders"
    resource_name = "Reminders"

    def __init__(self, service: RemindersService, *, id: str | None = None) -> None:
        super().__init__(service, id=id)

    def _fetch_content(self) -> list:
        return self._service.open_reminders()

    def _render_granted_content(self, content: list) -> ComposeResult:
        reminders = content
        if not reminders:
            yield Label("No open reminders.", classes="empty-state", markup=False)
            return

        for reminder in reminders:
            yield Label(f"- {reminder.title}", classes="reminder-item", markup=False)
