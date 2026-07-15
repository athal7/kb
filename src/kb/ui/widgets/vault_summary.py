"""Vault-wide entity counts.

Deliberately minimal for this first pass: a full multi-screen vault browser
(person/project/product detail views) is future work. Today's goal is a
navigable dashboard, not a complete browser.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label

from kb.core.index import VaultIndex


class VaultSummaryPane(Vertical):
    """People/project/product counts from a built VaultIndex.

    Rendered as a single line rather than three stacked Labels — this pane
    docks as a slim top info bar (see app.tcss), and a one-line strip reads
    as a status bar where a three-line stack would read as a mostly-empty
    card.
    """

    def __init__(self, index: VaultIndex, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._index = index

    def compose(self) -> ComposeResult:
        counts = (
            f"People: {len(self._index.all_people())}   "
            f"Projects: {len(self._index.all_projects())}   "
            f"Products: {len(self._index.all_products())}"
        )
        yield Label(counts)
