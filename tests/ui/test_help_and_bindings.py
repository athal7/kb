"""Dashboard-level keybindings: help modal, refresh, and the reserved act-on-item key.

Exercised through Dashboard.BINDINGS and App.run_test() rather than calling the
action_* methods directly, so a binding typo (e.g. "?" instead of Textual's
"question_mark" key name) would actually be caught.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from kb.core.actionitems import ActionItemsFile, load_action_items
from kb.core.index import VaultIndex
from kb.platform.fakes import FakeCalendarService, FakeRemindersService
from kb.ui.app import Dashboard
from kb.ui.screens.dashboard import DashboardScreen
from kb.ui.screens.help import HelpScreen
from tests.ui.dashboard_factory import build_dashboard

VAULT = Path(__file__).resolve().parents[1] / "fixtures" / "vault"

ACTION_ITEMS_SAMPLE = """# Open Action Items

## Ongoing / Unresolved
- [ ] Original item
"""


def _dashboard(**overrides) -> Dashboard:
    kwargs = dict(
        index=VaultIndex.build(VAULT),
        action_items=ActionItemsFile.parse(ACTION_ITEMS_SAMPLE).items,
        calendar_service=FakeCalendarService(),
        reminders_service=FakeRemindersService(),
    )
    kwargs.update(overrides)
    return build_dashboard(**kwargs)


class DescribeDashboardBindings:
    def it_declares_the_expected_keys_and_visibility(self):
        bindings = {b.key: b for b in Dashboard.BINDINGS}

        assert bindings["q"].action == "quit"
        assert bindings["q"].show is True
        assert bindings["question_mark"].action == "help"
        assert bindings["question_mark"].show is True
        assert bindings["r"].action == "refresh"
        assert bindings["r"].show is True
        assert bindings["f5"].action == "refresh"
        assert bindings["f5"].show is False
        assert bindings["x"].action == "act_on_item"
        assert bindings["x"].show is True
        assert bindings["space"].action == "act_on_item"
        assert bindings["space"].show is False


class DescribeHelpModal:
    async def it_pushes_the_help_screen_on_question_mark(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            await pilot.press("question_mark")
            top_screen = app.screen

        assert isinstance(top_screen, HelpScreen)

    async def it_dismisses_back_to_the_dashboard_on_q_without_quitting_the_app(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            await pilot.press("question_mark")
            await pilot.press("q")
            top_screen = app.screen
            still_running = app.is_running

        assert isinstance(top_screen, DashboardScreen)
        assert still_running


class DescribeActOnItem:
    async def it_notifies_that_the_action_is_not_implemented_yet(self):
        app = _dashboard()
        calls: list[tuple[str, dict]] = []
        app.notify = lambda message, **kwargs: calls.append((message, kwargs))

        async with app.run_test() as pilot:
            await pilot.press("x")

        assert calls
        message, kwargs = calls[0]
        assert message == "Not implemented yet"
        assert kwargs.get("severity") == "information"


class DescribeRefresh:
    async def it_rescans_the_vault_and_replaces_the_screen_when_kb_root_is_set(self, tmp_path):
        kb_root = tmp_path / "vault"
        shutil.copytree(VAULT, kb_root)

        app = build_dashboard(
            index=VaultIndex.build(kb_root),
            action_items=load_action_items(kb_root),
            kb_root=kb_root,
        )

        async with app.run_test() as pilot:
            original_screen = app.screen
            (kb_root / "action-items.md").write_text(
                "# Open Action Items\n\n"
                "## Ongoing / Unresolved\n"
                "- [ ] Freshly added item\n"
            )

            await pilot.press("r")
            await app.workers.wait_for_complete()
            await pilot.pause()

            item_texts = [
                label.content for label in app.screen.query("#action-items-pane .action-item")
            ]
            replaced_screen = app.screen

        assert item_texts == ["- Freshly added item"]
        assert replaced_screen is not original_screen
        assert isinstance(replaced_screen, DashboardScreen)

    async def it_warns_instead_of_crashing_when_kb_root_is_not_set(self):
        app = _dashboard(kb_root=None)
        calls: list[tuple[str, dict]] = []
        app.notify = lambda message, **kwargs: calls.append((message, kwargs))

        async with app.run_test() as pilot:
            await pilot.press("r")

        assert calls
        message, kwargs = calls[0]
        assert "KB_ROOT" in message
        assert kwargs.get("severity") == "warning"


class DescribeQuit:
    async def it_quits_the_app_when_q_is_pressed_with_no_modal_open(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            await pilot.press("q")

        assert not app.is_running
