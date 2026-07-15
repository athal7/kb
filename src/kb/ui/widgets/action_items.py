"""Read-only display of open action items, grouped by source header.

Phase 1 is read-only: `core/actionitems.py` already supports toggling a checkbox
line, but the dashboard doesn't expose that yet (Phase 2 write-back). This widget
only ever shows items where `checked` is False, and orders groups most-recent
first — the whole point of the pane is "what's still open," so a stale group
buried under an undated "Ongoing" bucket would defeat the purpose.
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


class ActionItemsPane(VerticalScroll):
    """Open action items grouped by source header, most recent group first."""

    BORDER_TITLE = "Action Items"

    # See AccessGatedPane's copy of this same pair for why it's duplicated
    # here rather than factored into a shared mixin.
    BINDINGS = [
        Binding("j", "scroll_down", "Scroll down", show=False),
        Binding("k", "scroll_up", "Scroll up", show=False),
    ]

    def __init__(self, items: list[ActionItem], *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._open_items = [item for item in items if not item.checked]

    def compose(self) -> ComposeResult:
        if not self._open_items:
            yield Label(
                "No open action items.", classes="empty-state", markup=False
            )
            return

        by_group: dict[str, list[ActionItem]] = {}
        for item in self._open_items:
            by_group.setdefault(_group_name(item), []).append(item)

        for group in _ordered_group_names(self._open_items):
            yield Label(group, classes="action-items-group", markup=False)
            for item in by_group[group]:
                yield Label(f"- {item.text}", classes="action-item", markup=False)
