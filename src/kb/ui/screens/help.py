"""Modal help screen listing kb-tui's keybindings.

Pushed by Dashboard.action_help (bound to `?`) and dismissed by `q`/`escape`/`?`
again. Dismissing pops this screen back to the dashboard underneath — it never
calls app.exit(), so `q` here must not be confused with the app-level `q` that
quits kb-tui entirely (see Dashboard.BINDINGS in app.py).
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

_HELP_TEXT = """\
[b]Global[/b]
  q            Quit
  ?            Help
  r, f5        Refresh
  x, space     Act on item (reserved)

[b]Navigation[/b]
  tab          Focus next pane
  shift+tab    Focus previous pane

[b]Within a pane[/b]
  j/k, ↑/↓     Scroll
  pgup/pgdn    Page up / page down
  home/end     Jump to top / bottom
"""


class HelpScreen(ModalScreen):
    """A dismissible modal listing kb-tui's keybindings."""

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }

    HelpScreen > Container {
        width: 60%;
        height: auto;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    """

    # "?" is the key Textual names "question_mark" (see keys._character_to_key),
    # not the literal string "?" — binding "?" here would silently never fire.
    BINDINGS = [
        Binding("question_mark", "dismiss", "Close help", show=False),
        Binding("escape", "dismiss", "Close help", show=False),
        Binding("q", "dismiss", "Close help", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Container():
            yield Static(_HELP_TEXT, markup=True)
