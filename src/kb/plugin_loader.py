"""Discover plugins and assemble the dashboard's pane registry.

Discovery uses the standard ``importlib.metadata.entry_points(group="kb.plugins")``
mechanism — the same pattern pytest/flake8/ruff plugins use. Discovery reads
distribution *metadata* only; nothing is imported until ``EntryPoint.load()`` is
called, and that happens *only* for plugins named in the enabled list. So a
discovered-but-disabled plugin never imports its module or its heavy dependencies
(e.g. pyobjc-framework-EventKit).

The registry is a flat ``{pane_id: PaneSpec}`` merged from the always-present
`CorePlugin` plus every enabled, successfully-loaded external plugin. A plugin that
fails to load (wrong platform, missing dep) or errors while producing panes is
logged and skipped — it must never take the whole dashboard down.
"""

from __future__ import annotations

import logging
from importlib.metadata import EntryPoint, entry_points

from kb.core.actionitems import ActionItem
from kb.plugins import PaneSpec, Plugin, PluginContext
from kb.ui.core_plugin import CorePlugin

ENTRY_POINT_GROUP = "kb.plugins"

_log = logging.getLogger(__name__)


def discover_plugins() -> dict[str, EntryPoint]:
    """Enumerate installed ``kb.plugins`` entry points by name (metadata only)."""
    return {ep.name: ep for ep in entry_points(group=ENTRY_POINT_GROUP)}


def build_pane_registry(
    *,
    context: PluginContext,
    action_items: list[ActionItem],
    enabled_plugins: list[str],
    discovered: dict[str, EntryPoint],
) -> dict[str, PaneSpec]:
    """Merge core panes with the panes of every enabled, loadable plugin.

    Later panes with a duplicate id would overwrite earlier ones; ids are
    namespaced by plugin to avoid that in practice.
    """
    registry: dict[str, PaneSpec] = {}

    plugins: list[Plugin] = [CorePlugin(action_items=action_items)]
    plugins.extend(_load_enabled(enabled_plugins, discovered))

    for plugin in plugins:
        try:
            specs = plugin.panes(context)
        except Exception:  # noqa: BLE001 - a bad plugin must not crash the app
            _log.warning(
                "plugin %r failed to produce panes; skipping",
                getattr(plugin, "id", plugin),
                exc_info=True,
            )
            continue
        for spec in specs:
            registry[spec.id] = spec

    return registry


def _load_enabled(
    enabled_plugins: list[str], discovered: dict[str, EntryPoint]
) -> list[Plugin]:
    loaded: list[Plugin] = []
    for name in enabled_plugins:
        entry_point = discovered.get(name)
        if entry_point is None:
            _log.warning("plugin %r is enabled but was not discovered; skipping", name)
            continue
        try:
            plugin_class = entry_point.load()
            loaded.append(plugin_class())
        except Exception:  # noqa: BLE001 - a broken plugin must not crash the app
            _log.warning("plugin %r failed to load; skipping", name, exc_info=True)
    return loaded
