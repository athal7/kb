"""The dashboard screen: builds its grid from a pane registry and layout config.

compose() no longer hardcodes which panes exist — it places whatever `PaneSpec`s
`layout_rows` names, looked up in `pane_registry`. That is what makes a plugin's
pane and a core pane interchangeable: both are just entries in the same dict,
and DashboardScreen has no idea which is which.

`kb.vault-summary` is the one exception: it is rendered as a slim docked-top bar
rather than a grid cell (see app.tcss), so it is placed outside the Grid if
present in the registry, and skipped if it also happens to appear in
`layout_rows` — there is exactly one of it, no matter how it's referenced.
"""

from __future__ import annotations

import logging
from collections import Counter

from textual.app import ComposeResult
from textual.containers import Grid
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, Header

from kb.core.index import VaultIndex
from kb.plugins import PaneSpec
from kb.ui.widgets.command_bar import CommandBar
from kb.ui.widgets.people_search import PeopleSearch

_VAULT_SUMMARY_ID = "kb.vault-summary"

_log = logging.getLogger(__name__)


class DashboardScreen(Screen):
    """Composes the docked vault summary plus a grid of registry-driven panes."""

    def __init__(
        self,
        *,
        index: VaultIndex,
        pane_registry: dict[str, PaneSpec],
        layout_rows: list[list[str]],
    ) -> None:
        super().__init__()
        self._index = index
        self._pane_registry = pane_registry
        self._layout_rows = layout_rows

    def compose(self) -> ComposeResult:
        yield Header()

        vault_summary = self._pane_registry.get(_VAULT_SUMMARY_ID)
        if vault_summary is not None:
            yield vault_summary.factory()

        columns = max((len(row) for row in self._layout_rows), default=1) or 1
        rows = len(self._layout_rows) or 1
        occurrences = Counter(
            pane_id
            for row in self._layout_rows
            for pane_id in row
            if pane_id != _VAULT_SUMMARY_ID
        )

        with Grid(id="dashboard-grid") as grid:
            grid.styles.grid_size_columns = columns
            grid.styles.grid_size_rows = rows
            built: set[str] = set()
            for row in self._layout_rows:
                for pane_id in row:
                    if pane_id == _VAULT_SUMMARY_ID or pane_id in built:
                        continue
                    built.add(pane_id)
                    widget = self._build_grid_pane(pane_id, occurrences[pane_id])
                    if widget is not None:
                        yield widget

        yield CommandBar(id="command-bar")
        yield PeopleSearch(self._index, id="people-search")
        yield Footer()

    def _build_grid_pane(self, pane_id: str, occurrence_count: int) -> Widget | None:
        spec = self._pane_registry.get(pane_id)
        if spec is None:
            _log.warning(
                "layout references pane %r, which is not registered; skipping", pane_id
            )
            return None

        widget = spec.factory()
        widget.add_class("dashboard-pane")

        span = max(occurrence_count, spec.default_row_span)
        if span > 1:
            widget.styles.row_span = span

        return widget
