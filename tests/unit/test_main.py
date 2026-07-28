"""kb-tui entry point wiring.

build_app() is the seam tested here: main() itself just calls build_app().run(),
which would start Textual's real event loop and can't be exercised in a test
harness. build_app() is where KB_ROOT resolution, vault scanning, and service
construction actually happen, so that's what needs a test double for KB_ROOT.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kb.config import InvalidVaultError
from kb.platform.eventkit_services import EventKitCalendarService, EventKitRemindersService
from kb.ui.app import Dashboard
from kb.ui.widgets.calendar_pane import CalendarPane
from kb.ui.widgets.reminders_pane import RemindersPane

VAULT = Path(__file__).resolve().parents[1] / "fixtures" / "vault"


class DescribeBuildApp:
    def it_constructs_a_dashboard_wired_to_the_resolved_vault(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(VAULT))
        from kb.__main__ import build_app

        app = build_app()

        assert isinstance(app, Dashboard)
        assert len(app._index.all_people()) == 4

    def it_wires_real_eventkit_backed_calendar_and_reminders_services(self, monkeypatch):
        # The app no longer holds calendar/reminders services directly — they're
        # closed over inside the pane registry's factories (see CorePlugin).
        # Building the actual pane widgets is the only way to prove the real
        # EventKit-backed services made it all the way through the registry,
        # rather than some fake left over from a test default.
        monkeypatch.setenv("KB_ROOT", str(VAULT))
        from kb.__main__ import build_app

        app = build_app()

        calendar_pane = app._pane_registry["calendar.upcoming"].factory()
        reminders_pane = app._pane_registry["calendar.reminders"].factory()

        assert isinstance(calendar_pane, CalendarPane)
        assert isinstance(calendar_pane._service, EventKitCalendarService)
        assert isinstance(reminders_pane, RemindersPane)
        assert isinstance(reminders_pane._service, EventKitRemindersService)

    def it_loads_open_action_items_from_the_vaults_action_items_file(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(VAULT))
        from kb.__main__ import build_app

        app = build_app()

        assert any("Sentinel" in item.text for item in app._action_items)

    def it_wires_the_resolved_kb_root_onto_the_dashboard_for_refresh(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(VAULT))
        from kb.__main__ import build_app

        app = build_app()

        assert app._kb_root == VAULT

    def it_raises_when_kb_root_does_not_look_like_a_vault(self, monkeypatch, tmp_path):
        monkeypatch.setenv("KB_ROOT", str(tmp_path))
        from kb.__main__ import build_app

        with pytest.raises(InvalidVaultError):
            build_app()
