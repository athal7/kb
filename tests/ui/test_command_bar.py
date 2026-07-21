"""The `:` command bar: trigger, cancel, dispatch, and the command registry.

Exercised through App.run_test()/Pilot rather than calling action_* methods or
commands.resolve() directly, so a binding typo (e.g. the literal ":" instead of
Textual's "colon" key name) would actually be caught — see the same discipline
applied to "?" in test_help_and_bindings.py.
"""

from __future__ import annotations

from pathlib import Path

from textual.widgets import Input

from kb.core.actionitems import ActionItemsFile
from kb.core.index import VaultIndex
from kb.platform.fakes import FakeCalendarService, FakeRemindersService
from kb.ui.app import Dashboard
from kb.ui.screens.help import HelpScreen
from kb.ui.widgets.command_bar import CommandBar
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


async def _submit(pilot, text: str) -> None:
    """Type text into the already-open command bar and press Enter to submit it."""
    bar_input = pilot.app.screen.query_one(CommandBar).query_one(Input)
    bar_input.value = text
    await pilot.press("enter")


class DescribeCommandBarTrigger:
    async def it_shows_and_focuses_the_bar_on_colon(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            await pilot.press("colon")
            bar = app.screen.query_one(CommandBar)
            bar_input = bar.query_one(Input)

            assert bar.display is True
            assert app.focused is bar_input

    async def it_hides_without_dispatching_on_escape_and_restores_prior_focus(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            pane = app.screen.query_one("#action-items-pane")
            pane.focus()
            await pilot.pause()

            await pilot.press("colon")
            bar = app.screen.query_one(CommandBar)
            await pilot.press("escape")

            assert bar.display is False
            assert app.focused is pane

    async def it_clears_the_input_text_after_escape(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            await pilot.press("colon")
            bar = app.screen.query_one(CommandBar)
            bar.query_one(Input).value = "some stale text"
            await pilot.press("escape")

            assert bar.query_one(Input).value == ""


class DescribeCommandDispatch:
    async def it_quits_the_app_on_q(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            await pilot.press("colon")
            await _submit(pilot, "q")

        assert not app.is_running

    async def it_quits_the_app_on_quit(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            await pilot.press("colon")
            await _submit(pilot, "quit")

        assert not app.is_running

    async def it_calls_action_refresh_on_r(self):
        app = _dashboard(kb_root=None)
        calls: list[tuple[str, dict]] = []
        app.notify = lambda message, **kwargs: calls.append((message, kwargs))

        async with app.run_test() as pilot:
            await pilot.press("colon")
            await _submit(pilot, "r")

        assert calls
        message, kwargs = calls[0]
        assert "KB_ROOT" in message
        assert kwargs.get("severity") == "warning"

    async def it_calls_action_refresh_on_refresh(self):
        app = _dashboard(kb_root=None)
        calls: list[tuple[str, dict]] = []
        app.notify = lambda message, **kwargs: calls.append((message, kwargs))

        async with app.run_test() as pilot:
            await pilot.press("colon")
            await _submit(pilot, "refresh")

        assert calls
        message, kwargs = calls[0]
        assert "KB_ROOT" in message
        assert kwargs.get("severity") == "warning"

    async def it_pushes_the_help_screen_on_h(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            await pilot.press("colon")
            await _submit(pilot, "h")

            assert isinstance(app.screen, HelpScreen)

    async def it_pushes_the_help_screen_on_help(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            await pilot.press("colon")
            await _submit(pilot, "help")

            assert isinstance(app.screen, HelpScreen)

    async def it_hides_and_clears_the_bar_after_a_successful_dispatch(self):
        app = _dashboard(kb_root=None)

        async with app.run_test() as pilot:
            await pilot.press("colon")
            bar = app.screen.query_one(CommandBar)
            await _submit(pilot, "refresh")

            assert bar.display is False
            assert bar.query_one(Input).value == ""

    async def it_warns_on_an_unknown_command(self):
        app = _dashboard()
        calls: list[tuple[str, dict]] = []
        app.notify = lambda message, **kwargs: calls.append((message, kwargs))

        async with app.run_test() as pilot:
            await pilot.press("colon")
            await _submit(pilot, "bogus")

        assert calls
        message, kwargs = calls[-1]
        assert message == "Unknown command: bogus"
        assert kwargs.get("severity") == "warning"

    async def it_hides_and_clears_the_bar_after_an_unknown_command(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            await pilot.press("colon")
            bar = app.screen.query_one(CommandBar)
            await _submit(pilot, "bogus")

            assert bar.display is False
            assert bar.query_one(Input).value == ""


class DescribeGotoCommand:
    async def it_notifies_when_the_named_person_is_found(self):
        app = _dashboard()
        calls: list[tuple[str, dict]] = []
        app.notify = lambda message, **kwargs: calls.append((message, kwargs))

        async with app.run_test() as pilot:
            await pilot.press("colon")
            await _submit(pilot, "goto Elena")

        assert calls
        message, kwargs = calls[-1]
        assert message == "Found: Elena"
        assert kwargs.get("severity") == "information"

    async def it_warns_when_no_such_entity_exists(self):
        app = _dashboard()
        calls: list[tuple[str, dict]] = []
        app.notify = lambda message, **kwargs: calls.append((message, kwargs))

        async with app.run_test() as pilot:
            await pilot.press("colon")
            await _submit(pilot, "goto Nonexistent")

        assert calls
        message, kwargs = calls[-1]
        assert message == "No such person, project, or product: Nonexistent"
        assert kwargs.get("severity") == "warning"

    async def it_warns_with_usage_when_no_argument_given(self):
        app = _dashboard()
        calls: list[tuple[str, dict]] = []
        app.notify = lambda message, **kwargs: calls.append((message, kwargs))

        async with app.run_test() as pilot:
            await pilot.press("colon")
            await _submit(pilot, "goto")

        assert calls
        message, kwargs = calls[-1]
        assert message == "Usage: :goto <name>"
        assert kwargs.get("severity") == "warning"

    async def it_finds_a_person_from_a_typo_via_fuzzy_fallback(self):
        app = _dashboard()
        calls: list[tuple[str, dict]] = []
        app.notify = lambda message, **kwargs: calls.append((message, kwargs))

        async with app.run_test() as pilot:
            await pilot.press("colon")
            # "anandd" is an unambiguous typo — only Priya Anand is close.
            await _submit(pilot, "goto anandd")

        assert calls
        message, kwargs = calls[-1]
        assert message == "Found: Priya Anand"
        assert kwargs.get("severity") == "information"

    async def it_offers_ranked_suggestions_when_several_plausibly_match(self):
        app = _dashboard()
        calls: list[tuple[str, dict]] = []
        app.notify = lambda message, **kwargs: calls.append((message, kwargs))

        async with app.run_test() as pilot:
            await pilot.press("colon")
            # "na" is a substring shared by both "Elena" and "Priya Anand".
            await _submit(pilot, "goto na")

        assert calls
        message, _kwargs = calls[-1]
        assert message.startswith("Did you mean: ")
        assert "Elena" in message
        assert "Priya Anand" in message

    async def it_still_warns_when_nothing_even_fuzzily_matches(self):
        app = _dashboard()
        calls: list[tuple[str, dict]] = []
        app.notify = lambda message, **kwargs: calls.append((message, kwargs))

        async with app.run_test() as pilot:
            await pilot.press("colon")
            await _submit(pilot, "goto zzzzxqptw")

        assert calls
        message, kwargs = calls[-1]
        assert message == "No such person, project, or product: zzzzxqptw"
        assert kwargs.get("severity") == "warning"
