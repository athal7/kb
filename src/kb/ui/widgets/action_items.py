"""Display of open and in-progress action items, grouped by source header.

Supports keyboard selection (up/down/k/j keys) and highlights the currently active
selected item. Rendering of items indicates status (in-progress uses `[-]`, todo uses `-`).
"""

from __future__ import annotations

import re

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Label

from kb.core.actionitems import ActionItem

_GROUP_DATE = re.compile(r"^From (\d{4}-\d{2}-\d{2})")

_UNGROUPED = "Ungrouped"


def _group_name(item: ActionItem) -> str:
    return item.source_group or _UNGROUPED


def _ordered_group_names(open_items: list[ActionItem]) -> list[str]:
    """Distinct group names, dated groups newest-first then undated groups.

    Undated groups (e.g. "Ongoing / Unresolved") keep their first-seen order at
    the end, since there's no date to rank them by.
    """
    seen: list[str] = []
    for item in open_items:
        name = _group_name(item)
        if name not in seen:
            seen.append(name)

    dated = [g for g in seen if _GROUP_DATE.match(g)]
    undated = [g for g in seen if not _GROUP_DATE.match(g)]
    dated.sort(key=lambda g: _GROUP_DATE.match(g).group(1), reverse=True)
    return dated + undated


class ActionItemLabel(Label):
    """A label representing a single ActionItem in the TUI."""
    def __init__(self, content: str, item: ActionItem, **kwargs) -> None:
        super().__init__(content, **kwargs)
        self.item = item


class ActionItemsPane(VerticalScroll):
    """Open/in-progress action items grouped by source header, most recent group first."""

    BORDER_TITLE = "Action Items"

    # We must support j/k for scroll_down/scroll_up when checking bindings.
    # To satisfy both requirements: "j/k/up/down" for cursor selection, and "j/k" for scroll fallback?
    # Actually, the requirement is "support keyboard cursor navigation (up/down/k/j)".
    # The failing test asserts:
    # "assert jk_bindings['j'].action == 'scroll_down'" on ActionItemsPane.
    # Since we are overriding BINDINGS on ActionItemsPane, we have redefined j/k to do cursor selection.
    # But wait, the test `it_marks_jk_bindings_as_hidden_on_every_scrollable_pane` asserts that ActionItemsPane has:
    # j/k mapped to scroll_down/scroll_up.
    # Wait, can we satisfy both?
    # Let's check: "j/k" is standard textual scroll bindings on VerticalScroll, but ActionItemsPane has custom bindings.
    # Wait! If we use a different key or we map j/k to custom actions that also scroll?
    # Actually, if we map j/k to cursor_down/cursor_up, then scroll_down/scroll_up is no longer mapped to j/k on ActionItemsPane.
    # But the test specifically tests ActionItemsPane! Let's read the test again:
    # `assert jk_bindings["j"].action == "scroll_down"`
    # Why does the test check that? Because prior to this change, ActionItemsPane was read-only and didn't support selection.
    # So it just scroll-slept. Now we want cursor selection!
    # If we want cursor selection, then j/k should move the cursor!
    # If j/k moves the cursor, does it also scroll? Yes, our `_update_selection` calls `self.scroll_to_widget(label, animate=False)`.
    # Let's modify the test or keep j/k for scrolling? No, the user explicitly asked:
    # "keyboard cursor navigation (up/down/k/j)"
    # If we change `j/k` to perform cursor navigation, then they don't do `scroll_down` directly; they do `cursor_down`, which then handles scrolling to the selection.
    # We should update `test_scroll_bindings.py` to reflect that `j/k` on ActionItemsPane now performs `cursor_down`/`cursor_up` instead of `scroll_down`/`scroll_up`.
    BINDINGS = [
        Binding("up", "cursor_up", "Cursor Up", show=False),
        Binding("down", "cursor_down", "Cursor Down", show=False),
        Binding("k", "cursor_up", "Cursor Up", show=False),
        Binding("j", "cursor_down", "Cursor Down", show=False),
    ]

    def __init__(self, items: list[ActionItem], *, id: str | None = None) -> None:
        super().__init__(id=id)
        # We only show items that are not completed (checked is False)
        self._open_items = [item for item in items if not item.checked]
        self._selected_index: int | None = 0 if self._open_items else None
        self.can_focus = True

    def compose(self) -> ComposeResult:
        if not self._open_items:
            yield Label(
                "No open action items.", classes="empty-state", markup=False
            )
            return

        by_group: dict[str, list[ActionItem]] = {}
        for item in self._open_items:
            by_group.setdefault(_group_name(item), []).append(item)

        item_idx = 0
        for group in _ordered_group_names(self._open_items):
            yield Label(group, classes="action-items-group", markup=False)
            for item in by_group[group]:
                prefix = "[-] " if item.in_progress else "- "
                classes = "action-item"
                if item.in_progress:
                    classes += " -in-progress"
                if item_idx == self._selected_index:
                    classes += " -selected"

                yield ActionItemLabel(
                    f"{prefix}{item.text}",
                    item,
                    classes=classes,
                    markup=False,
                    id=f"action-item-lbl-{item.line_no}"
                )
                item_idx += 1

    @property
    def selected_item(self) -> ActionItem | None:
        if self._selected_index is not None and 0 <= self._selected_index < len(self._open_items):
            return self._open_items[self._selected_index]
        return None

    def action_cursor_up(self) -> None:
        if not self._open_items or self._selected_index is None:
            return
        if self._selected_index > 0:
            self._selected_index -= 1
            self._update_selection()

    def action_cursor_down(self) -> None:
        if not self._open_items or self._selected_index is None:
            return
        if self._selected_index < len(self._open_items) - 1:
            self._selected_index += 1
            self._update_selection()

    def _update_selection(self) -> None:
        labels = list(self.query(ActionItemLabel))
        for idx, label in enumerate(labels):
            label.remove_class("-selected")
            if idx == self._selected_index:
                label.add_class("-selected")
                self.scroll_to_widget(label, animate=False)
