"""j/k vim-style scroll bindings on the focusable panes.

Asserted as functional equivalence to the arrow keys Textual already binds
(scroll_down/scroll_up), not as a reimplementation of scrolling — j/k should
move the scroll offset by exactly the same amount as down/up.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from kb.core.actionitems import ActionItemsFile
from kb.core.index import VaultIndex
from kb.platform.fakes import FakeCalendarService, FakeRemindersService
from kb.platform.models import CalendarEvent, Reminder
from kb.ui.app import Dashboard
from tests.ui.dashboard_factory import build_dashboard

VAULT = Path(__file__).resolve().parents[1] / "fixtures" / "vault"

_EVENT_TIME = datetime(2026, 7, 14, 9, 0)

# Enough rows to overflow a small terminal and make scrolling observable.
_MANY_EVENTS = [
    CalendarEvent(title=f"Event {i}", start=_EVENT_TIME, end=_EVENT_TIME, calendar_name="Work")
    for i in range(40)
]
_MANY_REMINDERS = [Reminder(title=f"Reminder {i}", list_name="Inbox") for i in range(40)]
_MANY_ACTION_ITEMS = ActionItemsFile.parse(
    "## Ongoing / Unresolved\n" + "\n".join(f"- [ ] item {i}" for i in range(40)) + "\n"
).items


def _dashboard(**overrides) -> Dashboard:
    kwargs = dict(
        index=VaultIndex.build(VAULT),
        action_items=_MANY_ACTION_ITEMS,
        calendar_service=FakeCalendarService(events=_MANY_EVENTS),
        reminders_service=FakeRemindersService(reminders=_MANY_REMINDERS),
    )
    kwargs.update(overrides)
    return build_dashboard(**kwargs)


async def _settle(pilot) -> None:
    """Wait for CalendarPane/RemindersPane's off-thread access-resolution worker."""
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


async def _press_and_settle(pilot, key: str) -> None:
    """Press a key and wait for the resulting scroll animation to finish.

    scroll_up/scroll_down animate by default, so scroll_offset only reflects
    the final position once the animation completes — reading it right after
    press() would race the tween.
    """
    await pilot.press(key)
    await pilot.wait_for_scheduled_animations()


class DescribeVimScrollOnCalendarPane:
    async def it_scrolls_down_the_same_amount_as_the_down_arrow(self):
        app = _dashboard()

        async with app.run_test(size=(80, 20)) as pilot:
            await _settle(pilot)
            pane = app.screen.query_one("#calendar-pane")
            pane.focus()
            await pilot.pause()

            await _press_and_settle(pilot, "down")
            after_down = pane.scroll_offset.y

            pane.scroll_home(animate=False)
            await pilot.pause()

            await _press_and_settle(pilot, "j")
            after_j = pane.scroll_offset.y

        assert after_j == after_down
        assert after_j > 0

    async def it_scrolls_up_the_same_amount_as_the_up_arrow(self):
        app = _dashboard()

        async with app.run_test(size=(80, 20)) as pilot:
            await _settle(pilot)
            pane = app.screen.query_one("#calendar-pane")
            pane.focus()
            pane.scroll_end(animate=False)
            await pilot.pause()
            end_offset = pane.scroll_offset.y

            await _press_and_settle(pilot, "up")
            after_up = pane.scroll_offset.y

            pane.scroll_end(animate=False)
            await pilot.pause()

            await _press_and_settle(pilot, "k")
            after_k = pane.scroll_offset.y

        assert after_k == after_up
        assert after_k < end_offset


class DescribeVimScrollOnRemindersPane:
    async def it_scrolls_down_the_same_amount_as_the_down_arrow(self):
        app = _dashboard()

        async with app.run_test(size=(80, 20)) as pilot:
            await _settle(pilot)
            pane = app.screen.query_one("#reminders-pane")
            pane.focus()
            await pilot.pause()

            await _press_and_settle(pilot, "down")
            after_down = pane.scroll_offset.y

            pane.scroll_home(animate=False)
            await pilot.pause()

            await _press_and_settle(pilot, "j")
            after_j = pane.scroll_offset.y

        assert after_j == after_down
        assert after_j > 0


class DescribeVimScrollOnActionItemsPane:
    async def it_scrolls_down_the_same_amount_as_the_down_arrow(self):
        app = _dashboard()

        async with app.run_test(size=(80, 20)) as pilot:
            pane = app.screen.query_one("#action-items-pane")
            pane.focus()
            await pilot.pause()

            await _press_and_settle(pilot, "down")
            after_down = pane.scroll_offset.y

            pane.scroll_home(animate=False)
            await pilot.pause()

            await _press_and_settle(pilot, "j")
            after_j = pane.scroll_offset.y

        assert after_j == after_down
        assert after_j > 0

    async def it_scrolls_up_the_same_amount_as_the_up_arrow(self):
        app = _dashboard()

        async with app.run_test(size=(80, 20)) as pilot:
            pane = app.screen.query_one("#action-items-pane")
            pane.focus()
            pane.scroll_end(animate=False)
            await pilot.pause()
            end_offset = pane.scroll_offset.y

            await _press_and_settle(pilot, "up")
            after_up = pane.scroll_offset.y

            pane.scroll_end(animate=False)
            await pilot.pause()

            await _press_and_settle(pilot, "k")
            after_k = pane.scroll_offset.y

        assert after_k == after_up
        assert after_k < end_offset


class DescribeVimScrollBindingsAreHiddenFromFooter:
    def it_marks_jk_bindings_as_hidden_on_every_scrollable_pane(self):
        from kb.ui.widgets.access_gated_pane import AccessGatedPane
        from kb.ui.widgets.action_items import ActionItemsPane

        for pane_cls in (AccessGatedPane, ActionItemsPane):
            jk_bindings = {b.key: b for b in pane_cls.BINDINGS}
            assert jk_bindings["j"].show is False
            assert jk_bindings["k"].show is False
            assert jk_bindings["j"].action == "scroll_down"
            assert jk_bindings["k"].action == "scroll_up"
