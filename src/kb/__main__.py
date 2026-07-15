"""kb-tui entry point.

Wires the pure-Python VaultIndex, the real EventKit-backed services, config,
and plugin discovery into a pane registry, then hands that registry to the
Dashboard app. The app only ever depends on `PaneSpec`s in a registry dict —
never on EventKit, the plugin loader, or config parsing — so this is the one
place that knows which concrete calendar/reminders backend is in play and
which plugins/layout the user has configured. Swapping the real EventKit
services for fakes (e.g. for UI development without a TCC prompt) is a
one-line change here, not a UI rewrite.

Config (`~/.config/kb/config.toml`) is read once, here, at startup — not
re-read on every Dashboard.action_refresh. A refresh re-scans the vault and
rebuilds the pane registry from the *same* enabled plugins/services/layout, so
a config edit takes effect on the next launch, not the next refresh keypress.
"""

from __future__ import annotations

from kb.config import resolve_kb_root
from kb.core.actionitems import ActionItem, load_action_items
from kb.core.index import VaultIndex
from kb.platform.eventkit_services import EventKitCalendarService, EventKitRemindersService
from kb.plugin_config import default_config_path, load_config
from kb.plugin_loader import build_pane_registry, discover_plugins
from kb.plugins import PaneSpec, PluginContext
from kb.ui.app import Dashboard


def build_app() -> Dashboard:
    """Resolve KB_ROOT, scan the vault, and construct the Dashboard app.

    Split from main() so tests can construct the app without starting
    Textual's event loop.
    """
    kb_root = resolve_kb_root(None, validate=True)
    index = VaultIndex.build(kb_root)
    action_items = load_action_items(kb_root)

    config = load_config(default_config_path())
    discovered = discover_plugins()
    calendar_service = EventKitCalendarService()
    reminders_service = EventKitRemindersService()

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
            enabled_plugins=config.enabled_plugins,
            discovered=discovered,
        )

    return Dashboard(
        index=index,
        action_items=action_items,
        pane_registry=rebuild_pane_registry(index, action_items),
        layout_rows=config.layout_rows,
        rebuild_pane_registry=rebuild_pane_registry,
        kb_root=kb_root,
    )


def main() -> None:
    build_app().run()


if __name__ == "__main__":
    main()
