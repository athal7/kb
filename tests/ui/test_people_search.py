"""The `/` people search: live-filtered fuzzy picker over the full people roster.

Exercised through App.run_test()/Pilot rather than calling action_* methods or
VaultIndex.fuzzy_people() directly, so a binding typo (e.g. the literal "/" instead
of Textual's "slash" key name) would actually be caught — see the same discipline
applied in test_command_bar.py.
"""

from __future__ import annotations

from pathlib import Path

from textual.widgets import Input, ListView

from kb.core.actionitems import ActionItemsFile
from kb.core.index import VaultIndex
from kb.platform.fakes import FakeCalendarService, FakeRemindersService
from kb.ui.app import Dashboard
from kb.ui.widgets.people_search import PeopleSearch
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


def _result_labels(widget: PeopleSearch) -> list[str]:
    return [item.query_one("Label").content for item in widget.query_one(ListView).children]


class DescribePeopleSearchTrigger:
    async def it_shows_and_focuses_the_input_on_slash(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            await pilot.press("slash")
            search = app.screen.query_one(PeopleSearch)
            search_input = search.query_one(Input)

            assert search.display is True
            assert app.focused is search_input

    async def it_populates_the_full_people_roster_on_open(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            await pilot.press("slash")
            search = app.screen.query_one(PeopleSearch)

            assert set(_result_labels(search)) == {
                "Andre",
                "Andrew Thal",
                "Kate Silverstein",
                "Stephen Golub",
            }

    async def it_hides_without_notifying_on_escape_and_restores_prior_focus(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            pane = app.screen.query_one("#action-items-pane")
            pane.focus()
            await pilot.pause()

            await pilot.press("slash")
            search = app.screen.query_one(PeopleSearch)
            await pilot.press("escape")

            assert search.display is False
            assert app.focused is pane

    async def it_clears_the_query_text_after_escape(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            await pilot.press("slash")
            search = app.screen.query_one(PeopleSearch)
            search.query_one(Input).value = "some stale text"
            await pilot.press("escape")

            assert search.query_one(Input).value == ""

    async def it_does_not_notify_on_escape(self):
        app = _dashboard()
        calls: list[tuple[str, dict]] = []
        app.notify = lambda message, **kwargs: calls.append((message, kwargs))

        async with app.run_test() as pilot:
            await pilot.press("slash")
            await pilot.press("escape")

        assert calls == []


class DescribePeopleSearchLiveFilter:
    async def it_narrows_results_to_a_fuzzy_match_as_the_user_types(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            await pilot.press("slash")
            search = app.screen.query_one(PeopleSearch)
            search.query_one(Input).value = "silverstien"
            await pilot.pause()

            assert _result_labels(search) == ["Kate Silverstein"]

    async def it_shows_an_empty_list_for_a_query_matching_nobody(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            await pilot.press("slash")
            search = app.screen.query_one(PeopleSearch)
            search.query_one(Input).value = "zzzzxqptw"
            await pilot.pause()

            assert _result_labels(search) == []

    async def it_reverts_to_the_full_roster_when_the_query_is_cleared(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            await pilot.press("slash")
            search = app.screen.query_one(PeopleSearch)
            search.query_one(Input).value = "silverstien"
            await pilot.pause()
            search.query_one(Input).value = ""
            await pilot.pause()

            assert len(_result_labels(search)) == 4

    async def it_clears_stale_results_when_reopened_after_a_previous_query(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            await pilot.press("slash")
            search = app.screen.query_one(PeopleSearch)
            search.query_one(Input).value = "silverstien"
            await pilot.pause()
            await pilot.press("escape")

            await pilot.press("slash")

            assert search.query_one(Input).value == ""
            assert len(_result_labels(search)) == 4


class DescribePeopleSearchConfirm:
    async def it_notifies_the_highlighted_persons_display_name_on_enter(self):
        app = _dashboard()
        calls: list[tuple[str, dict]] = []
        app.notify = lambda message, **kwargs: calls.append((message, kwargs))

        async with app.run_test() as pilot:
            await pilot.press("slash")
            search = app.screen.query_one(PeopleSearch)
            search.query_one(Input).value = "silverstien"
            await pilot.pause()
            await pilot.press("enter")

        assert calls
        message, kwargs = calls[-1]
        assert message == "Selected: Kate Silverstein"
        assert kwargs.get("severity") == "information"

    async def it_hides_and_restores_prior_focus_after_a_confirmed_selection(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            pane = app.screen.query_one("#action-items-pane")
            pane.focus()
            await pilot.pause()

            await pilot.press("slash")
            search = app.screen.query_one(PeopleSearch)
            search.query_one(Input).value = "silverstien"
            await pilot.pause()
            await pilot.press("enter")

            assert search.display is False
            assert app.focused is pane

    async def it_moves_the_highlight_with_arrow_keys_without_losing_input_focus(self):
        app = _dashboard()
        calls: list[tuple[str, dict]] = []
        app.notify = lambda message, **kwargs: calls.append((message, kwargs))

        async with app.run_test() as pilot:
            await pilot.press("slash")
            search = app.screen.query_one(PeopleSearch)
            search_input = search.query_one(Input)

            await pilot.press("down")
            assert app.focused is search_input

            await pilot.press("enter")

        # Roster is display-sorted: Andre, Andrew Thal, Kate Silverstein, Stephen Golub.
        # One "down" from the first item highlights the second.
        assert calls
        message, _ = calls[-1]
        assert message == "Selected: Andrew Thal"
