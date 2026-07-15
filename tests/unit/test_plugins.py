"""The plugin contract: PaneSpec, PluginContext, and the Plugin protocol.

These are the shared shapes both the built-in core panes and external plugin
distributions implement. The contract lives in kb.plugins and depends only on
Textual + stdlib — never on core/ or platform/ — so a plugin author can import it
without pulling the whole app in.
"""

from __future__ import annotations

from textual.widget import Widget
from textual.widgets import Label

from kb.plugins import PaneSpec, Plugin, PluginContext


class DescribePaneSpec:
    def it_bundles_a_factory_with_placement_metadata(self):
        spec = PaneSpec(
            id="demo.hello",
            title="Hello",
            factory=lambda: Label("hi"),
        )

        assert spec.id == "demo.hello"
        assert spec.title == "Hello"
        assert spec.default_weight == 1
        assert spec.default_row_span == 1

    def it_builds_a_fresh_widget_each_time_the_factory_is_called(self):
        spec = PaneSpec(id="demo.hello", title="Hello", factory=lambda: Label("hi"))

        first = spec.factory()
        second = spec.factory()

        assert isinstance(first, Widget)
        assert first is not second

    def it_accepts_explicit_size_hints(self):
        spec = PaneSpec(
            id="demo.big",
            title="Big",
            factory=lambda: Label("x"),
            default_weight=3,
            default_row_span=2,
        )

        assert spec.default_weight == 3
        assert spec.default_row_span == 2


class DescribePluginContext:
    def it_carries_the_vault_index_and_kb_root(self):
        sentinel_index = object()
        sentinel_root = object()

        context = PluginContext(vault_index=sentinel_index, kb_root=sentinel_root)

        assert context.vault_index is sentinel_index
        assert context.kb_root is sentinel_root

    def it_defaults_calendar_and_reminders_services_to_none(self):
        context = PluginContext(vault_index=object(), kb_root=object())

        assert context.calendar_service is None
        assert context.reminders_service is None

    def it_carries_the_calendar_and_reminders_services_when_supplied(self):
        sentinel_calendar = object()
        sentinel_reminders = object()

        context = PluginContext(
            vault_index=object(),
            kb_root=object(),
            calendar_service=sentinel_calendar,
            reminders_service=sentinel_reminders,
        )

        assert context.calendar_service is sentinel_calendar
        assert context.reminders_service is sentinel_reminders


class DescribePluginProtocol:
    def it_recognises_a_class_that_provides_id_and_panes_as_a_plugin(self):
        class DemoPlugin:
            id = "demo"

            def panes(self, context: PluginContext) -> list[PaneSpec]:
                return [PaneSpec(id="demo.hello", title="Hello", factory=lambda: Label("hi"))]

        plugin = DemoPlugin()

        assert isinstance(plugin, Plugin)

    def it_rejects_an_object_missing_the_panes_method(self):
        class NotAPlugin:
            id = "nope"

        assert not isinstance(NotAPlugin(), Plugin)

    def it_collects_specs_from_a_plugins_panes_method(self):
        class DemoPlugin:
            id = "demo"

            def panes(self, context: PluginContext) -> list[PaneSpec]:
                return [PaneSpec(id="demo.hello", title="Hello", factory=lambda: Label("hi"))]

        context = PluginContext(vault_index=object(), kb_root=object())
        specs = DemoPlugin().panes(context)

        assert [s.id for s in specs] == ["demo.hello"]
