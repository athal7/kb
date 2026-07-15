"""The built-in CorePlugin exposes the KB-vault panes through the plugin contract.

Core panes are not special-cased: they register the same way an external plugin
would, so the dashboard has a single code path for "here is a pane, place it".
CorePlugin owns the vault-summary and action-items panes; its factories build the
existing VaultSummaryPane / ActionItemsPane against the context's vault index and
the action items handed to it.
"""

from __future__ import annotations

from pathlib import Path

from kb.core.actionitems import ActionItemsFile
from kb.core.index import VaultIndex
from kb.platform.fakes import FakeCalendarService, FakeRemindersService
from kb.plugins import Plugin, PluginContext
from kb.ui.core_plugin import CorePlugin
from kb.ui.widgets.action_items import ActionItemsPane
from kb.ui.widgets.calendar_pane import CalendarPane
from kb.ui.widgets.reminders_pane import RemindersPane
from kb.ui.widgets.vault_summary import VaultSummaryPane

VAULT = Path(__file__).resolve().parents[1] / "fixtures" / "vault"


def _context(**overrides) -> PluginContext:
    kwargs = dict(vault_index=VaultIndex.build(VAULT), kb_root=VAULT)
    kwargs.update(overrides)
    return PluginContext(**kwargs)


class DescribeCorePlugin:
    def it_is_a_plugin(self):
        assert isinstance(CorePlugin(action_items=[]), Plugin)

    def it_exposes_the_vault_summary_and_action_items_panes(self):
        plugin = CorePlugin(action_items=[])

        ids = [spec.id for spec in plugin.panes(_context())]

        assert ids == ["kb.vault-summary", "kb.action-items"]

    def it_builds_a_vault_summary_widget_from_the_context_index(self):
        plugin = CorePlugin(action_items=[])
        specs = {spec.id: spec for spec in plugin.panes(_context())}

        widget = specs["kb.vault-summary"].factory()

        assert isinstance(widget, VaultSummaryPane)

    def it_builds_an_action_items_widget_from_the_supplied_items(self):
        items = ActionItemsFile.parse(
            "# Open Action Items\n\n## From 2026-07-13\n- [ ] Ship it\n"
        ).items
        plugin = CorePlugin(action_items=items)
        specs = {spec.id: spec for spec in plugin.panes(_context())}

        widget = specs["kb.action-items"].factory()

        assert isinstance(widget, ActionItemsPane)

    def it_builds_a_fresh_widget_on_each_factory_call(self):
        plugin = CorePlugin(action_items=[])
        spec = plugin.panes(_context())[0]

        assert spec.factory() is not spec.factory()

    def it_omits_the_calendar_pane_when_the_context_has_no_calendar_service(self):
        plugin = CorePlugin(action_items=[])

        ids = [spec.id for spec in plugin.panes(_context())]

        assert "calendar.upcoming" not in ids

    def it_omits_the_reminders_pane_when_the_context_has_no_reminders_service(self):
        plugin = CorePlugin(action_items=[])

        ids = [spec.id for spec in plugin.panes(_context())]

        assert "calendar.reminders" not in ids

    def it_exposes_a_calendar_pane_when_the_context_carries_a_calendar_service(self):
        plugin = CorePlugin(action_items=[])
        context = _context(calendar_service=FakeCalendarService())
        specs = {spec.id: spec for spec in plugin.panes(context)}

        widget = specs["calendar.upcoming"].factory()

        assert isinstance(widget, CalendarPane)

    def it_exposes_a_reminders_pane_when_the_context_carries_a_reminders_service(self):
        plugin = CorePlugin(action_items=[])
        context = _context(reminders_service=FakeRemindersService())
        specs = {spec.id: spec for spec in plugin.panes(context)}

        widget = specs["calendar.reminders"].factory()

        assert isinstance(widget, RemindersPane)
