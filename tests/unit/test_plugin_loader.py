"""Discovery of external plugins + assembly of the pane registry.

Entry points in the ``kb.plugins`` group are *discovered* from distribution
metadata (cheap, no import). A plugin is only *loaded* — its module imported and
class instantiated — when its name appears in the enabled list, so a
discovered-but-disabled plugin never imports its heavy dependencies. The core
plugin is always merged in. A plugin that fails to load or errors is skipped with a
warning, never crashing the dashboard.
"""

from __future__ import annotations

from pathlib import Path

from kb.core.index import VaultIndex
from kb.plugin_loader import build_pane_registry
from kb.plugins import PaneSpec, PluginContext

VAULT = Path(__file__).resolve().parents[1] / "fixtures" / "vault"


def _context() -> PluginContext:
    return PluginContext(vault_index=VaultIndex.build(VAULT), kb_root=VAULT)


class _FakeEntryPoint:
    """Stands in for importlib.metadata.EntryPoint.

    ``load()`` returns the plugin class (or raises to simulate a broken import).
    Records whether it was loaded so tests can assert a disabled plugin is never
    touched.
    """

    def __init__(self, name, plugin_class=None, load_error=None):
        self.name = name
        self._plugin_class = plugin_class
        self._load_error = load_error
        self.loaded = False

    def load(self):
        self.loaded = True
        if self._load_error is not None:
            raise self._load_error
        return self._plugin_class


class _StubPlugin:
    id = "stub"

    def panes(self, context):
        return [PaneSpec(id="stub.pane", title="Stub", factory=lambda: object())]


class DescribeBuildPaneRegistry:
    def it_always_includes_the_core_panes(self):
        registry = build_pane_registry(
            context=_context(),
            action_items=[],
            enabled_plugins=[],
            discovered={},
        )

        assert "kb.vault-summary" in registry
        assert "kb.action-items" in registry

    def it_maps_pane_ids_to_pane_specs(self):
        registry = build_pane_registry(
            context=_context(),
            action_items=[],
            enabled_plugins=[],
            discovered={},
        )

        assert isinstance(registry["kb.action-items"], PaneSpec)

    def it_loads_and_includes_an_enabled_plugins_panes(self):
        ep = _FakeEntryPoint("stub", plugin_class=_StubPlugin)

        registry = build_pane_registry(
            context=_context(),
            action_items=[],
            enabled_plugins=["stub"],
            discovered={"stub": ep},
        )

        assert ep.loaded is True
        assert "stub.pane" in registry

    def it_never_loads_a_discovered_but_disabled_plugin(self):
        # load_error would blow up if load() were ever called — proving a disabled
        # plugin's module (and its heavy deps) is never imported.
        ep = _FakeEntryPoint("stub", load_error=AssertionError("must not load"))

        registry = build_pane_registry(
            context=_context(),
            action_items=[],
            enabled_plugins=[],
            discovered={"stub": ep},
        )

        assert ep.loaded is False
        assert "stub.pane" not in registry

    def it_skips_a_plugin_whose_import_fails_without_crashing(self):
        ep = _FakeEntryPoint("broken", load_error=ImportError("no EventKit here"))

        registry = build_pane_registry(
            context=_context(),
            action_items=[],
            enabled_plugins=["broken"],
            discovered={"broken": ep},
        )

        # Core panes still present; the broken plugin is simply absent.
        assert "kb.action-items" in registry
        assert not any(pane_id.startswith("broken") for pane_id in registry)

    def it_ignores_an_enabled_name_that_was_never_discovered(self):
        registry = build_pane_registry(
            context=_context(),
            action_items=[],
            enabled_plugins=["ghost"],
            discovered={},
        )

        assert "kb.action-items" in registry
