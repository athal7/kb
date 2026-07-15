"""The plugin contract for dashboard panes.

Both the built-in core panes and external plugin distributions register panes by
implementing the same `Plugin` protocol and handing back `PaneSpec`s. Keeping the
contract here — depending only on Textual and stdlib, never on `core/` or
`platform/` — means a third-party plugin author can `from kb.plugins import
Plugin, PaneSpec` without importing the vault index, EventKit, or anything else the
app happens to wire up.

Why the shapes are this small:

- `PaneSpec.factory` is a zero-arg callable that returns a *fresh* widget. A plugin
  closes over whatever services it needs inside the factory (a calendar plugin
  constructs its EventKit-backed service there), so there is no dependency-injection
  container — plugins own their own services. Textual widgets are single-use in a
  DOM, so a refresh must build a new one; hence a factory rather than a cached
  instance.
- `PluginContext` hands over the two things a plugin genuinely cannot build itself:
  the already-scanned vault index and the resolved KB root. A calendar plugin
  ignores it; a KB-vault plugin reads `vault_index`. Typed as `object` so this
  module stays free of a `core` import (the concrete type is `VaultIndex`/`Path`,
  duck-typed at the use site).
- `Plugin` is a `runtime_checkable` Protocol, not an ABC: plugins are structurally
  typed and never share implementation, matching the existing
  `CalendarService`/`RemindersService` Protocol style in platform/interfaces.py.

Keybindings/commands are deliberately out of scope for v1 — a pane's own Textual
`BINDINGS` already give it focus-local keys, and adding an optional `commands` field
to `PaneSpec` later is additive and non-breaking.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from textual.widget import Widget


@dataclass(frozen=True)
class PaneSpec:
    """Everything the dashboard needs to place and build one pane.

    `id` is namespaced (e.g. "kb.action-items", "calendar.upcoming") so config can
    reference panes unambiguously and two plugins can't collide. `default_weight`
    and `default_row_span` are soft hints the layout may honor; the config's row
    layout has the final say on arrangement.
    """

    id: str
    title: str
    factory: Callable[[], Widget]
    default_weight: int = 1
    default_row_span: int = 1


@dataclass(frozen=True)
class PluginContext:
    """Read-only, core-owned handles a plugin may need to build its panes.

    `vault_index` is a `VaultIndex` and `kb_root` is a `Path`; typed as `object`
    here to keep this module free of a `core` import (see module docstring).

    `calendar_service`/`reminders_service` are `None` unless the caller supplies
    real ones (a `CalendarService`/`RemindersService`) — a plugin that doesn't
    care about them (most don't) never has to know they exist, and a test
    building a bare-bones context for a non-calendar assertion doesn't have to
    fabricate fakes it never uses.
    """

    vault_index: object
    kb_root: object
    calendar_service: object = None
    reminders_service: object = None


@runtime_checkable
class Plugin(Protocol):
    """A source of dashboard panes.

    `id` matches the plugin's entry-point name and the config enable list. `panes`
    is called once at startup with a `PluginContext` and returns the specs this
    plugin contributes.
    """

    id: str

    def panes(self, context: PluginContext) -> list[PaneSpec]: ...
