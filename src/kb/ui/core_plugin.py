"""The built-in plugin for the core KB-vault panes.

Core panes register through the same `Plugin`/`PaneSpec` contract an external
plugin uses, rather than being hardcoded into the dashboard's compose(). That way
the dashboard has one code path — "collect specs from enabled plugins, then place
them by config" — and moving a core pane is the same operation as placing a plugin
pane. `CorePlugin` is always present and always enabled; it is not discovered via
entry points.

It is constructed with the already-loaded action items (the vault index comes from
the PluginContext) so its factories can build fresh `ActionItemsPane` /
`VaultSummaryPane` widgets on demand — Textual widgets are single-use in a DOM, so
a refresh builds new ones.

Calendar/reminders panes live here too, not in a separate plugin, since they
haven't been extracted into their own distribution yet — that extraction is
future work. They're conditional on the context carrying the corresponding
service: a caller that never wires up EventKit (most unit tests) gets the two
KB-vault panes only, with no dummy service to fabricate.
"""

from __future__ import annotations

from kb.core.actionitems import ActionItem
from kb.core.index import VaultIndex
from kb.plugins import PaneSpec, PluginContext
from kb.ui.widgets.action_items import ActionItemsPane
from kb.ui.widgets.calendar_pane import CalendarPane
from kb.ui.widgets.reminders_pane import RemindersPane
from kb.ui.widgets.vault_summary import VaultSummaryPane


class CorePlugin:
    """Exposes the vault-summary, action-items, calendar, and reminders panes."""

    id = "kb"

    def __init__(self, *, action_items: list[ActionItem]) -> None:
        self._action_items = action_items

    def panes(self, context: PluginContext) -> list[PaneSpec]:
        index = context.vault_index
        assert isinstance(index, VaultIndex)  # documents the duck-typed contract
        action_items = self._action_items

        specs = [
            PaneSpec(
                id="kb.vault-summary",
                title="Vault Summary",
                factory=lambda: VaultSummaryPane(index, id="vault-summary"),
            ),
            PaneSpec(
                id="kb.action-items",
                title="Action Items",
                factory=lambda: ActionItemsPane(action_items, id="action-items-pane"),
                default_row_span=2,
            ),
        ]

        if context.calendar_service is not None:
            calendar_service = context.calendar_service
            specs.append(
                PaneSpec(
                    id="calendar.upcoming",
                    title="Upcoming Events",
                    factory=lambda: CalendarPane(calendar_service, id="calendar-pane"),
                )
            )

        if context.reminders_service is not None:
            reminders_service = context.reminders_service
            specs.append(
                PaneSpec(
                    id="calendar.reminders",
                    title="Reminders",
                    factory=lambda: RemindersPane(reminders_service, id="reminders-pane"),
                )
            )

        return specs
