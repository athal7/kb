"""Shared Dashboard construction for tests/ui/*.

Every UI test builds its `Dashboard` through `build_dashboard()` rather than
constructing `Dashboard(pane_registry=..., layout_rows=...)` by hand — that
would mean every test re-deriving the same registry-building boilerplate
(`PluginContext` + `build_pane_registry` + `DEFAULT_LAYOUT_ROWS`) that
`__main__.build_app()` already does for the real app. Routing tests through
the same construction path as production means a test failure here reflects a
real wiring bug, not a divergence between the test double and the real thing.

Also wires a real `rebuild_pane_registry` closure (mirroring `build_app()`'s),
so `Dashboard.action_refresh` is exercised end-to-end in tests exactly as it
runs in production — a refresh test that only got a stale, un-rebuildable
registry would validate a Dashboard that can never happen for a real user.
"""

from __future__ import annotations

from pathlib import Path

from kb.core.actionitems import ActionItem
from kb.core.index import VaultIndex
from kb.platform.fakes import FakeCalendarService, FakeRemindersService
from kb.plugin_config import DEFAULT_LAYOUT_ROWS
from kb.plugin_loader import build_pane_registry
from kb.plugins import PaneSpec, PluginContext
from kb.ui.app import Dashboard

VAULT = Path(__file__).resolve().parents[1] / "fixtures" / "vault"


def build_dashboard(
    *,
    index: VaultIndex | None = None,
    action_items: list[ActionItem] | None = None,
    calendar_service: object = None,
    reminders_service: object = None,
    kb_root: Path | None = VAULT,
    enabled_plugins: list[str] | None = None,
    layout_rows: list[list[str]] | None = None,
) -> Dashboard:
    index = index if index is not None else VaultIndex.build(VAULT)
    action_items = action_items if action_items is not None else []
    calendar_service = calendar_service if calendar_service is not None else FakeCalendarService()
    reminders_service = (
        reminders_service if reminders_service is not None else FakeRemindersService()
    )
    enabled_plugins = enabled_plugins if enabled_plugins is not None else []
    layout_rows = layout_rows if layout_rows is not None else DEFAULT_LAYOUT_ROWS

    def rebuild_pane_registry(
        index: VaultIndex, action_items: list[ActionItem]
    ) -> dict[str, PaneSpec]:
        context = PluginContext(
            vault_index=index,
            kb_root=kb_root,
            calendar_service=calendar_service,
            reminders_service=reminders_service,
        )
        return build_pane_registry(
            context=context,
            action_items=action_items,
            enabled_plugins=enabled_plugins,
            discovered={},
        )

    return Dashboard(
        index=index,
        action_items=action_items,
        pane_registry=rebuild_pane_registry(index, action_items),
        layout_rows=layout_rows,
        rebuild_pane_registry=rebuild_pane_registry,
        kb_root=kb_root,
    )
