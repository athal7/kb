"""The kb-tui Textual App.

Constructed with an already-built VaultIndex, the action items, and an
already-assembled pane registry + layout — never constructs a pane registry
itself and never imports objc/EventKit or the plugin loader. See __main__.py
for wiring plugin discovery, config, and the real vs. fake calendar/reminders
services into that registry; changing any of that is a change there, not here.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from textual import work
from textual.app import App
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import Input

from kb.core.actionitems import ActionItem, load_action_items
from kb.core.index import VaultIndex
from kb.plugins import PaneSpec
from kb.ui import commands
from kb.ui.screens.dashboard import DashboardScreen
from kb.ui.screens.help import HelpScreen
from kb.ui.widgets.command_bar import CommandBar
from kb.ui.widgets.people_search import PeopleSearch

PaneRegistry = dict[str, PaneSpec]
RegistryBuilder = Callable[[VaultIndex, list[ActionItem]], PaneRegistry]


class Dashboard(App):
    """kb-tui's single dashboard screen: action items, calendar, reminders, vault summary."""

    TITLE = "kb-tui"
    CSS_PATH = "app.tcss"

    # "?" is the key Textual names "question_mark" (see keys._character_to_key),
    # not the literal string "?" — binding "?" here would silently never fire.
    # Same discipline for ":" — Textual names it "colon", not the literal ":".
    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("question_mark", "help", "Help", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("f5", "refresh", "Refresh", show=False),
        Binding("x", "act_on_item", "Act", show=True),
        Binding("space", "act_on_item", "Act", show=False),
        Binding("colon", "open_command_line", "Command", show=True),
        Binding("slash", "open_search", "Search", show=True),
    ]

    def __init__(
        self,
        *,
        index: VaultIndex,
        action_items: list[ActionItem],
        pane_registry: PaneRegistry,
        layout_rows: list[list[str]],
        rebuild_pane_registry: RegistryBuilder | None = None,
        kb_root: Path | None = None,
    ) -> None:
        super().__init__()
        self._index = index
        self._action_items = action_items
        self._pane_registry = pane_registry
        self._layout_rows = layout_rows
        # Given a fresh index + action items, produces a fresh pane registry —
        # supplied by __main__.py, which is the only place that knows about
        # plugin discovery/config/enabled-plugins/services. Kept optional (like
        # kb_root) so tests exercising a fixed registry don't have to supply
        # one; refresh then just re-renders the existing registry's panes with
        # their original (already-closed-over) data.
        self._rebuild_pane_registry = rebuild_pane_registry
        # Only needed to re-scan the vault on refresh (see action_refresh) — kept
        # optional so tests that never exercise refresh don't have to supply one.
        self._kb_root = kb_root
        # Whatever had focus when the command bar or people search was opened,
        # so it can be restored on dismiss/dispatch instead of leaving focus on
        # the overlay. Only one of the two overlays is ever open at a time.
        self._focus_before_overlay: Widget | None = None
        # The specific CommandBar instance we opened — not re-looked-up via
        # self.screen at close time, since a handler like `:help` may have
        # pushed a new screen on top by then, and self.screen would point at
        # that new screen instead of the one the bar actually lives on.
        self._open_command_bar: CommandBar | None = None

    @property
    def index(self) -> VaultIndex:
        """Exposed so command handlers (see commands.py) can validate against it."""
        return self._index

    def on_mount(self) -> None:
        self.push_screen(
            DashboardScreen(
                index=self._index,
                pane_registry=self._pane_registry,
                layout_rows=self._layout_rows,
            )
        )

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_act_on_item(self) -> None:
        self.notify("Not implemented yet", severity="information")

    def action_open_command_line(self) -> None:
        self._open_command_line()

    def action_open_search(self) -> None:
        self._focus_before_overlay = self.focused
        self.screen.query_one(PeopleSearch).show_and_focus()

    def _open_command_line(self, prefill: str = "") -> None:
        self._focus_before_overlay = self.focused
        self._open_command_bar = self.screen.query_one(CommandBar)
        self._open_command_bar.show_and_focus(prefill)

    def on_command_bar_dismissed(self, message: CommandBar.Dismissed) -> None:
        message.stop()
        self._close_command_line()

    def on_people_search_dismissed(self, message: PeopleSearch.Dismissed) -> None:
        message.stop()
        self.screen.query_one(PeopleSearch).hide_and_clear()
        self._restore_focus()

    def on_input_submitted(self, message: Input.Submitted) -> None:
        if message.input.id != "command-bar-input":
            return
        message.stop()
        self._dispatch_command(message.value)

    def _dispatch_command(self, text: str) -> None:
        command, args = commands.resolve(text)
        if command is None:
            token = text.split()[0] if text.split() else text
            self.notify(f"Unknown command: {token}", severity="warning")
        else:
            command.handler(self, args)
        self._close_command_line()

    def _close_command_line(self) -> None:
        if self._open_command_bar is not None:
            self._open_command_bar.hide_and_clear()
            self._open_command_bar = None
        self._restore_focus()

    def _restore_focus(self) -> None:
        if self._focus_before_overlay is not None:
            self._focus_before_overlay.focus()
        self._focus_before_overlay = None

    def action_refresh(self) -> None:
        if self._kb_root is None:
            self.notify(
                "Refresh requires a KB_ROOT; not available in this session.",
                severity="warning",
            )
            return
        self._rescan_vault(self._kb_root)

    @work(thread=True)
    def _rescan_vault(self, kb_root: Path) -> None:
        """Re-scan the vault off the UI thread — see AccessGatedPane for why.

        A ~175-file scan is fast, but doing file I/O synchronously on the main
        thread still blocks Textual's message pump for however long it takes.
        """
        index = VaultIndex.build(kb_root)
        action_items = load_action_items(kb_root)
        self.call_from_thread(self._apply_refresh, index, action_items)

    def _apply_refresh(self, index: VaultIndex, action_items: list[ActionItem]) -> None:
        """Swap in freshly-scanned data by rebuilding the registry and screen.

        `rebuild_pane_registry` reuses the existing calendar/reminders services
        (rather than rebuilding them) — their AccessGatedPane workers re-run
        access_state()/fetch on the new screen's mount for free, no separate
        reminders/calendar refresh path needed. Layout config is deliberately
        not re-read here — see __main__.py's docstring — so `_layout_rows`
        carries over unchanged; only the panes it names get rebuilt.
        """
        self._index = index
        self._action_items = action_items
        if self._rebuild_pane_registry is not None:
            self._pane_registry = self._rebuild_pane_registry(index, action_items)
        self.pop_screen()
        self.push_screen(
            DashboardScreen(
                index=self._index,
                pane_registry=self._pane_registry,
                layout_rows=self._layout_rows,
            )
        )
