"""Dashboard app composition and pane rendering against the fixture vault.

Exercised via Textual's App.run_test() harness so panes are asserted against real
compose()/mount() behavior rather than hand-inspected dataclasses. Never points at
the real KB — always the synthetic fixture vault.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from textual.app import App
from textual.widgets import Label

from kb.core.actionitems import ActionItemsFile
from kb.core.index import VaultIndex
from kb.platform.fakes import FakeCalendarService, FakeRemindersService
from kb.platform.models import AccessState, CalendarEvent, Reminder
from kb.plugins import PaneSpec
from kb.ui.app import Dashboard
from kb.ui.screens.dashboard import DashboardScreen
from tests.ui.dashboard_factory import build_dashboard

VAULT = Path(__file__).resolve().parents[1] / "fixtures" / "vault"

ACTION_ITEMS_SAMPLE = """# Open Action Items

## From 2026-07-13 (Slack)
- [ ] **Diego**: Ship the dashboard
- [x] **Diego**: Already done, should not show

## From 2026-07-07 (Lumen Check-in)
- [ ] **Priya**: Follow up with [[Sentinel]] team — see [PR](https://x/1) LUMEN-1732

## Ongoing / Unresolved
- [ ] Storage migration — vendor timeline shifting
"""


def _event(title="Standup", start=None):
    start = start or datetime(2026, 7, 14, 9, 0)
    return CalendarEvent(
        title=title, start=start, end=start, calendar_name="Work"
    )


def _reminder(title="Ship the thing"):
    return Reminder(title=title, list_name="Inbox")


async def _settle(pilot) -> None:
    """Wait for a pane's off-thread access-resolution worker to finish.

    CalendarPane/RemindersPane resolve access_state()/request_access() in a
    @work(thread=True) worker (see access_gated_pane.py) rather than
    synchronously in compose(), and the resulting reactive update recomposes
    on the *next* message-pump idle rather than inline — so both the worker
    and one more pump cycle need to complete before assertions see the final
    render instead of the transient "checking"/"requesting" state.
    """
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def _dashboard(**overrides) -> Dashboard:
    kwargs = dict(
        index=VaultIndex.build(VAULT),
        action_items=ActionItemsFile.parse(ACTION_ITEMS_SAMPLE).items,
        calendar_service=FakeCalendarService(),
        reminders_service=FakeRemindersService(),
    )
    kwargs.update(overrides)
    return build_dashboard(**kwargs)


def _fake_pane_spec(pane_id: str, *, default_row_span: int = 1) -> PaneSpec:
    """A minimal PaneSpec for tests that only care about placement mechanics,
    not any real pane's content — proves DashboardScreen's compose() is
    genuinely generic, not secretly special-cased to the real KB panes.
    """
    widget_id = pane_id.replace(".", "-")
    return PaneSpec(
        id=pane_id,
        title=pane_id,
        factory=lambda: Label(pane_id, id=widget_id, markup=False),
        default_row_span=default_row_span,
    )


class _PaneRegistryHost(App):
    """Hosts a bare DashboardScreen against an arbitrary registry + layout,
    without any of Dashboard's bindings/commands — those are exercised
    elsewhere; this is only for DashboardScreen's placement mechanics.
    """

    def __init__(
        self, *, pane_registry: dict[str, PaneSpec], layout_rows: list[list[str]]
    ) -> None:
        super().__init__()
        self._pane_registry = pane_registry
        self._layout_rows = layout_rows

    def on_mount(self) -> None:
        self.push_screen(
            DashboardScreen(
                index=VaultIndex.build(VAULT),
                pane_registry=self._pane_registry,
                layout_rows=self._layout_rows,
            )
        )


class DescribeDashboardComposition:
    async def it_composes_without_error_against_the_fixture_vault(self):
        app = _dashboard()

        async with app.run_test():
            assert app.screen is not None

    async def it_shows_vault_entity_counts(self):
        app = _dashboard()

        async with app.run_test():
            summary = app.screen.query_one("#vault-summary")
            texts = [label.content for label in summary.query("Label")]

        assert any("4" in t and "People" in t for t in texts)
        assert any("2" in t and "Projects" in t for t in texts)


class DescribeActionItemsPane:
    async def it_shows_only_open_items_grouped_most_recent_first(self):
        app = _dashboard()

        async with app.run_test():
            group_labels = app.screen.query("#action-items-pane .action-items-group")
            groups = [label.content for label in group_labels]

        assert groups == [
            "From 2026-07-13 (Slack)",
            "From 2026-07-07 (Lumen Check-in)",
            "Ongoing / Unresolved",
        ]

    async def it_omits_checked_items_and_preserves_wikilink_and_link_text(self):
        app = _dashboard()

        async with app.run_test():
            item_texts = [
                label.content for label in app.screen.query("#action-items-pane .action-item")
            ]

        assert item_texts == [
            "- **Diego**: Ship the dashboard",
            "- **Priya**: Follow up with [[Sentinel]] team — see [PR](https://x/1) LUMEN-1732",
            "- Storage migration — vendor timeline shifting",
        ]

    async def it_shows_an_empty_state_when_there_are_no_open_items(self):
        app = _dashboard(action_items=[])

        async with app.run_test():
            empty = app.screen.query_one("#action-items-pane .empty-state")

        assert "No open action items" in empty.content


class DescribeCalendarPane:
    async def it_renders_titles_and_start_times_for_upcoming_events(self):
        events = [_event("Standup", datetime(2026, 7, 14, 9, 0))]
        app = _dashboard(calendar_service=FakeCalendarService(events=events))

        async with app.run_test() as pilot:
            await _settle(pilot)
            event_labels = app.screen.query("#calendar-pane .calendar-event")
            entries = [label.content for label in event_labels]

        assert entries == ["Jul 14 09:00 — Standup"]

    async def it_points_at_system_settings_when_access_is_denied(self):
        service = FakeCalendarService(events=[_event()], access_state=AccessState.DENIED)
        app = _dashboard(calendar_service=service)

        async with app.run_test() as pilot:
            await _settle(pilot)
            denied = app.screen.query_one("#calendar-pane .access-denied")
            events = app.screen.query("#calendar-pane .calendar-event")

        assert denied.content == (
            "Calendar access denied — grant it in "
            "System Settings > Privacy & Security > Calendar."
        )
        assert len(events) == 0

    async def it_points_at_system_settings_when_access_is_restricted(self):
        service = FakeCalendarService(events=[_event()], access_state=AccessState.RESTRICTED)
        app = _dashboard(calendar_service=service)

        async with app.run_test() as pilot:
            await _settle(pilot)
            denied = app.screen.query_one("#calendar-pane .access-denied")
            events = app.screen.query("#calendar-pane .calendar-event")

        assert denied.content == (
            "Calendar access denied — grant it in "
            "System Settings > Privacy & Security > Calendar."
        )
        assert len(events) == 0

    async def it_requests_access_and_renders_events_when_previously_undetermined(self):
        events = [_event("Standup", datetime(2026, 7, 14, 9, 0))]
        service = FakeCalendarService(
            events=events,
            access_state=AccessState.NOT_DETERMINED,
            access_state_after_request=AccessState.GRANTED,
        )
        app = _dashboard(calendar_service=service)

        async with app.run_test() as pilot:
            await _settle(pilot)
            event_labels = app.screen.query("#calendar-pane .calendar-event")
            entries = [label.content for label in event_labels]

        # Only reachable if the pane actually called request_access() — the
        # fake starts at NOT_DETERMINED and only moves to GRANTED once asked.
        assert entries == ["Jul 14 09:00 — Standup"]

    async def it_shows_the_denied_message_when_a_freshly_asked_user_declines(self):
        service = FakeCalendarService(
            events=[_event()],
            access_state=AccessState.NOT_DETERMINED,
            access_state_after_request=AccessState.DENIED,
        )
        app = _dashboard(calendar_service=service)

        async with app.run_test() as pilot:
            await _settle(pilot)
            denied = app.screen.query_one("#calendar-pane .access-denied")
            events = app.screen.query("#calendar-pane .calendar-event")

        assert "Calendar access denied" in denied.content
        assert len(events) == 0


class DescribeRemindersPane:
    async def it_renders_titles_of_open_reminders(self):
        reminders = [_reminder("Ship the thing")]
        app = _dashboard(reminders_service=FakeRemindersService(reminders=reminders))

        async with app.run_test() as pilot:
            await _settle(pilot)
            reminder_labels = app.screen.query("#reminders-pane .reminder-item")
            entries = [label.content for label in reminder_labels]

        assert entries == ["- Ship the thing"]

    async def it_points_at_system_settings_when_access_is_denied(self):
        service = FakeRemindersService(
            reminders=[_reminder()], access_state=AccessState.DENIED
        )
        app = _dashboard(reminders_service=service)

        async with app.run_test() as pilot:
            await _settle(pilot)
            denied = app.screen.query_one("#reminders-pane .access-denied")
            reminders = app.screen.query("#reminders-pane .reminder-item")

        assert denied.content == (
            "Reminders access denied — grant it in "
            "System Settings > Privacy & Security > Reminders."
        )
        assert len(reminders) == 0

    async def it_points_at_system_settings_when_access_is_restricted(self):
        service = FakeRemindersService(
            reminders=[_reminder()], access_state=AccessState.RESTRICTED
        )
        app = _dashboard(reminders_service=service)

        async with app.run_test() as pilot:
            await _settle(pilot)
            denied = app.screen.query_one("#reminders-pane .access-denied")
            reminders = app.screen.query("#reminders-pane .reminder-item")

        assert denied.content == (
            "Reminders access denied — grant it in "
            "System Settings > Privacy & Security > Reminders."
        )
        assert len(reminders) == 0

    async def it_requests_access_and_renders_reminders_when_previously_undetermined(self):
        reminders = [_reminder("Ship the thing")]
        service = FakeRemindersService(
            reminders=reminders,
            access_state=AccessState.NOT_DETERMINED,
            access_state_after_request=AccessState.GRANTED,
        )
        app = _dashboard(reminders_service=service)

        async with app.run_test() as pilot:
            await _settle(pilot)
            reminder_labels = app.screen.query("#reminders-pane .reminder-item")
            entries = [label.content for label in reminder_labels]

        # Only reachable if the pane actually called request_access() — the
        # fake starts at NOT_DETERMINED and only moves to GRANTED once asked.
        assert entries == ["- Ship the thing"]

    async def it_shows_the_denied_message_when_a_freshly_asked_user_declines(self):
        service = FakeRemindersService(
            reminders=[_reminder()],
            access_state=AccessState.NOT_DETERMINED,
            access_state_after_request=AccessState.DENIED,
        )
        app = _dashboard(reminders_service=service)

        async with app.run_test() as pilot:
            await _settle(pilot)
            denied = app.screen.query_one("#reminders-pane .access-denied")
            reminders = app.screen.query("#reminders-pane .reminder-item")

        assert "Reminders access denied" in denied.content
        assert len(reminders) == 0


GRID_PANE_IDS = ("#calendar-pane", "#action-items-pane", "#reminders-pane")


class DescribePaneStyling:
    async def it_gives_every_grid_pane_a_visible_border(self):
        app = _dashboard()

        async with app.run_test():
            panes = [app.screen.query_one(pane_id) for pane_id in GRID_PANE_IDS]

        assert all(pane.styles.border_top[0] for pane in panes)

    async def it_titles_each_grid_pane_border_with_its_purpose(self):
        app = _dashboard()

        async with app.run_test():
            titles = {
                pane_id: app.screen.query_one(pane_id).border_title
                for pane_id in GRID_PANE_IDS
            }

        assert titles == {
            "#calendar-pane": "Upcoming Events",
            "#action-items-pane": "Action Items",
            "#reminders-pane": "Reminders",
        }

    async def it_gives_the_action_items_pane_the_full_column_height(self):
        app = _dashboard()

        async with app.run_test():
            action_items = app.screen.query_one("#action-items-pane")
            calendar = app.screen.query_one("#calendar-pane")
            reminders = app.screen.query_one("#reminders-pane")

        assert action_items.styles.row_span == 2
        assert calendar.styles.row_span == 1
        assert reminders.styles.row_span == 1

    async def it_arranges_the_three_panes_in_a_two_by_two_grid(self):
        app = _dashboard()

        async with app.run_test():
            grid = app.screen.query_one("#dashboard-grid")

        assert (grid.styles.grid_size_columns, grid.styles.grid_size_rows) == (2, 2)

    async def it_keeps_the_action_items_pane_scrollable_for_overflowing_content(self):
        app = _dashboard()

        async with app.run_test():
            pane = app.screen.query_one("#action-items-pane")

        assert pane.styles.overflow_y == "auto"

    async def it_wraps_long_action_item_text_instead_of_clipping_it(self):
        long_text = "Marcus Webb's CHANGES_REQUESTED " * 10
        items = ActionItemsFile.parse(
            f"# Open Action Items\n\n## Ongoing / Unresolved\n- [ ] {long_text}\n"
        ).items
        app = _dashboard(action_items=items)

        async with app.run_test(size=(80, 24)):
            pane = app.screen.query_one("#action-items-pane")
            label = app.screen.query_one("#action-items-pane .action-item")
            label_size = label.size
            pane_size = pane.size

        assert label_size.width <= pane_size.width
        assert label_size.height > 1

    async def it_gives_a_focused_pane_a_visibly_different_border_color(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            pane = app.screen.query_one("#calendar-pane")
            other = app.screen.query_one("#action-items-pane")

            # CalendarPane auto-focuses on mount (Textual's AUTO_FOCUS), so
            # shift focus elsewhere first to get a genuinely unfocused baseline.
            other.focus()
            await pilot.pause()
            unfocused_color = pane.styles.border_top[1]

            pane.focus()
            await pilot.pause()
            focused_color = pane.styles.border_top[1]

        assert focused_color != unfocused_color

    async def it_never_gives_the_vault_summary_pane_a_focus_state(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            summary = app.screen.query_one("#vault-summary")

            for _ in range(len(GRID_PANE_IDS)):
                await pilot.press("tab")

            focused_ids = set()
            for _ in range(len(GRID_PANE_IDS)):
                await pilot.press("tab")
                focused_ids.add(app.screen.focused.id if app.screen.focused else None)

        assert summary.can_focus is False
        assert "vault-summary" not in focused_ids

    async def it_tab_cycles_between_exactly_the_three_grid_panes(self):
        app = _dashboard()

        async with app.run_test() as pilot:
            focused_ids = set()
            for _ in range(len(GRID_PANE_IDS)):
                await pilot.press("tab")
                focused_ids.add(app.screen.focused.id if app.screen.focused else None)

        assert focused_ids == set(GRID_PANE_IDS[i].lstrip("#") for i in range(len(GRID_PANE_IDS)))


class DescribeVaultSummaryLayout:
    async def it_composes_the_vault_summary_pane_outside_the_grid(self):
        app = _dashboard()

        async with app.run_test():
            grid = app.screen.query_one("#dashboard-grid")
            summary = app.screen.query_one("#vault-summary")
            # Captured while the tree is live — Grid.children is cleared on
            # screen teardown, so checking this after the `async with` block
            # exits would trivially pass regardless of the real composition.
            is_grid_child = summary in grid.children
            is_grid_parent = summary.parent is grid

        assert not is_grid_child
        assert not is_grid_parent

    async def it_docks_the_vault_summary_pane_to_the_top(self):
        app = _dashboard()

        async with app.run_test():
            summary = app.screen.query_one("#vault-summary")
            dock = summary.styles.dock

        assert dock == "top"

    async def it_sizes_the_vault_summary_pane_to_its_content_not_a_quadrant(self):
        app = _dashboard()

        async with app.run_test():
            summary = app.screen.query_one("#vault-summary")
            # Captured while the tree is live — Widget.size resets once the
            # screen tears down, so reading it after the `async with` block
            # exits would trivially pass regardless of the real layout.
            height = summary.size.height

        # A slim info bar is a handful of rows tall, nowhere near the ~10
        # rows a 2x2 quadrant would give it in the default 80x24 test size.
        assert height <= 3

    async def it_gives_the_vault_summary_pane_no_border(self):
        app = _dashboard()

        async with app.run_test():
            summary = app.screen.query_one("#vault-summary")
            has_border = bool(summary.styles.border_top[0])

        assert not has_border


class DescribeGenericPaneRegistryComposition:
    """DashboardScreen against a synthetic registry — proves the placement
    mechanism itself is generic, not just correct for the real KB panes it
    happens to be tested with everywhere else in this file.
    """

    async def it_renders_every_pane_named_in_layout_rows(self):
        registry = {
            "demo.a": _fake_pane_spec("demo.a"),
            "demo.b": _fake_pane_spec("demo.b"),
            "demo.c": _fake_pane_spec("demo.c"),
        }
        app = _PaneRegistryHost(
            pane_registry=registry,
            layout_rows=[["demo.a", "demo.b"], ["demo.a", "demo.c"]],
        )

        async with app.run_test():
            grid = app.screen.query_one("#dashboard-grid")
            ids = {child.id for child in grid.children}

        assert ids == {"demo-a", "demo-b", "demo-c"}

    async def it_builds_a_pane_repeated_across_rows_only_once(self):
        registry = {"demo.a": _fake_pane_spec("demo.a"), "demo.b": _fake_pane_spec("demo.b")}
        app = _PaneRegistryHost(
            pane_registry=registry,
            layout_rows=[["demo.a", "demo.b"], ["demo.a"]],
        )

        async with app.run_test():
            grid = app.screen.query_one("#dashboard-grid")
            # Counted while the tree is live — see the doc comment on
            # DescribeVaultSummaryLayout above for why a lazy DOMQuery must be
            # consumed inside the `async with` block, not after.
            match_count = len(grid.query("#demo-a"))

        assert match_count == 1

    async def it_spans_the_rows_a_pane_id_repeats_across(self):
        registry = {"demo.a": _fake_pane_spec("demo.a"), "demo.b": _fake_pane_spec("demo.b")}
        app = _PaneRegistryHost(
            pane_registry=registry,
            layout_rows=[["demo.a", "demo.b"], ["demo.a"]],
        )

        async with app.run_test():
            widget = app.screen.query_one("#demo-a")
            span = widget.styles.row_span

        assert span == 2

    async def it_honors_default_row_span_when_the_pane_appears_only_once(self):
        registry = {"demo.a": _fake_pane_spec("demo.a", default_row_span=3)}
        app = _PaneRegistryHost(pane_registry=registry, layout_rows=[["demo.a"]])

        async with app.run_test():
            widget = app.screen.query_one("#demo-a")
            span = widget.styles.row_span

        assert span == 3

    async def it_skips_a_pane_id_missing_from_the_registry_without_crashing(self):
        registry = {"demo.a": _fake_pane_spec("demo.a")}
        app = _PaneRegistryHost(
            pane_registry=registry,
            layout_rows=[["demo.a", "demo.missing"]],
        )

        async with app.run_test():
            assert app.screen is not None
            grid = app.screen.query_one("#dashboard-grid")
            ids = {child.id for child in grid.children}

        assert ids == {"demo-a"}

    async def it_logs_a_warning_for_a_pane_id_missing_from_the_registry(self, caplog):
        import logging

        registry: dict[str, PaneSpec] = {}
        app = _PaneRegistryHost(
            pane_registry=registry,
            layout_rows=[["demo.missing"]],
        )

        with caplog.at_level(logging.WARNING, logger="kb.ui.screens.dashboard"):
            async with app.run_test():
                pass

        assert any("demo.missing" in record.message for record in caplog.records)
