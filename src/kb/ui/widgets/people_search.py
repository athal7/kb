"""The `/` people search: a hidden-by-default live-filtered fuzzy person picker.

Sits above the Footer in DashboardScreen's compose order (see app.tcss for the
`display: none` default) and is shown/focused by Dashboard.action_open_search.
Mirrors CommandBar's show/hide/focus/dismiss plumbing: Escape posts Dismissed
rather than hiding itself directly, since restoring whatever widget had focus
before the search opened is Dashboard's (the App's) job, not this widget's.

The Input stays focused the whole time the search is open — arrow keys move the
ListView's highlight via bindings on this container (bubbling up past Input,
which doesn't bind up/down itself) rather than by shifting focus to the list,
so the user can keep typing immediately after tapping an arrow key.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.message import Message
from textual.widgets import Input, Label, ListItem, ListView

from kb.core.index import VaultIndex
from kb.core.models import EntityRef
from kb.ui.commands import _display_of

_INPUT_ID = "people-search-input"
_LIST_ID = "people-search-results"


class PeopleSearch(Container):
    """A `/`-triggered live-filtered fuzzy person picker, hidden until shown."""

    class Dismissed(Message):
        """Posted when the search closes, via Escape or a confirmed selection."""

    BINDINGS = [
        Binding("escape", "dismiss_search", "Cancel", show=False),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
    ]

    def __init__(self, index: VaultIndex, **kwargs) -> None:
        super().__init__(**kwargs)
        self._index = index
        self._results: list[EntityRef] = []

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Search people…", id=_INPUT_ID)
        yield ListView(id=_LIST_ID)

    def action_dismiss_search(self) -> None:
        self.post_message(self.Dismissed())

    def action_cursor_up(self) -> None:
        self.query_one(ListView).action_cursor_up()

    def action_cursor_down(self) -> None:
        self.query_one(ListView).action_cursor_down()

    def show_and_focus(self) -> None:
        self.display = True
        self.query_one(Input).value = ""
        self._filter("")
        self.query_one(Input).focus()

    def hide_and_clear(self) -> None:
        self.query_one(Input).value = ""
        self._filter("")
        self.display = False

    def on_input_changed(self, message: Input.Changed) -> None:
        if message.input.id != _INPUT_ID:
            return
        message.stop()
        self._filter(message.value)

    def on_input_submitted(self, message: Input.Submitted) -> None:
        if message.input.id != _INPUT_ID:
            return
        message.stop()
        self._confirm_selection()

    def _filter(self, query: str) -> None:
        self._results = self._index.fuzzy_people(query)
        list_view = self.query_one(ListView)
        list_view.clear()
        list_view.extend(ListItem(Label(_display_of(ref))) for ref in self._results)
        # clear() resets index to None and neither append() nor extend() ever
        # sets one on their own (ListView only seeds it from initial_index at
        # mount time) — without this, index stays None after every re-filter,
        # so the first arrow press only lands on the top result instead of
        # moving off of it, and Enter has nothing highlighted to confirm.
        list_view.index = 0 if self._results else None

    def _confirm_selection(self) -> None:
        index = self.query_one(ListView).index
        if index is None or not self._results:
            self.post_message(self.Dismissed())
            return
        ref = self._results[index]
        self.app.notify(f"Selected: {_display_of(ref)}", severity="information")
        self.post_message(self.Dismissed())
