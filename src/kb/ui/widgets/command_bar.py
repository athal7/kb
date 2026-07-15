"""The `:` command bar: a hidden-by-default Input for vim-style commands.

Sits above the Footer in DashboardScreen's compose order (see app.tcss for the
`display: none` default) and is shown/focused by Dashboard.action_open_command_line.
Escape posts Dismissed rather than hiding itself directly — hiding is paired with
restoring whatever widget had focus before the bar opened, and only Dashboard
(the App) tracks that prior-focus state.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.message import Message
from textual.widgets import Input

_INPUT_ID = "command-bar-input"


class CommandBar(Container):
    """A `:`-prefixed command-line input, hidden until explicitly shown."""

    class Dismissed(Message):
        """Posted when the bar is cancelled via Escape, with no command run."""

    BINDINGS = [
        Binding("escape", "dismiss_command_bar", "Cancel", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Input(placeholder=":command", id=_INPUT_ID)

    def action_dismiss_command_bar(self) -> None:
        self.post_message(self.Dismissed())

    def show_and_focus(self, prefill: str = "") -> None:
        self.display = True
        field = self.query_one(Input)
        field.value = prefill
        # Cursor to end so the user types after the seeded prefix (e.g. "goto ").
        field.cursor_position = len(prefill)
        field.focus()

    def hide_and_clear(self) -> None:
        self.query_one(Input).value = ""
        self.display = False
