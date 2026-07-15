"""Parse and byte-faithfully edit `action-items.md`.

The file is the Phase 1 / Phase 2 seam. It is a flat list of `## From <date> (source)`
groups plus an `## Ongoing / Unresolved` group, each holding `- [ ]` / `- [x]` items.
Items carry inline `[[wikilinks]]`, markdown `[text](url)` links, and plain-text Linear
refs (e.g. `0DIN-1732`), and are inconsistently prefixed with `**Person**:`.

Editing is line-surgical: the file's exact lines are retained and a toggle rewrites only
the single `[ ]`/`[x]` marker on the target line. We never round-trip through a markdown
AST, because that would reflow whitespace and confuse the daily enrichment run that reads
this same file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

ACTION_ITEMS_FILENAME = "action-items.md"

_HEADING = re.compile(r"^##\s+(.*?)\s*$")
_CHECKBOX = re.compile(r"^- \[([ xX])\]\s?(.*)$")
_BOLD_PREFIX = re.compile(r"^\*\*(.+?)\*\*:")
_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_LINEAR = re.compile(r"\b([0-9A-Z]+-\d+)\b")


@dataclass
class ActionItem:
    source_group: str | None
    checked: bool
    text: str
    raw_line: str
    line_no: int
    person_prefix: str | None
    wikilinks: list[str]
    external_links: list[str]
    linear_refs: list[str]


@dataclass
class ActionItemsFile:
    lines: list[str]
    trailing_newline: bool
    items: list[ActionItem] = field(default_factory=list)

    @classmethod
    def parse(cls, text: str) -> ActionItemsFile:
        trailing_newline = text.endswith("\n")
        # Split without swallowing structure; drop the final empty element that a
        # trailing newline produces so serialize() can reconstruct it exactly.
        raw = text.split("\n")
        if trailing_newline and raw and raw[-1] == "":
            raw = raw[:-1]

        items: list[ActionItem] = []
        current_group: str | None = None
        for i, line in enumerate(raw):
            h = _HEADING.match(line)
            if h:
                current_group = h.group(1)
                continue
            cb = _CHECKBOX.match(line)
            if not cb:
                continue
            checked = cb.group(1) in ("x", "X")
            body = cb.group(2)
            items.append(
                ActionItem(
                    source_group=current_group,
                    checked=checked,
                    text=body,
                    raw_line=line,
                    line_no=i,
                    person_prefix=cls._person_prefix(body),
                    wikilinks=_WIKILINK.findall(body),
                    external_links=_MD_LINK.findall(body),
                    linear_refs=_LINEAR.findall(body),
                )
            )

        return cls(lines=raw, trailing_newline=trailing_newline, items=items)

    @staticmethod
    def _person_prefix(body: str) -> str | None:
        m = _BOLD_PREFIX.match(body)
        return m.group(1) if m else None

    def serialize(self) -> str:
        text = "\n".join(self.lines)
        if self.trailing_newline:
            text += "\n"
        return text

    def toggle(self, item: ActionItem) -> None:
        """Flip the checkbox marker on `item`'s line, changing nothing else."""
        new_checked = not item.checked
        marker = "[x]" if new_checked else "[ ]"
        old_marker = "[x]" if item.checked else "[ ]"
        line = self.lines[item.line_no]
        # Replace only the first marker occurrence, preserving surrounding bytes.
        self.lines[item.line_no] = line.replace(old_marker, marker, 1)
        item.checked = new_checked
        item.raw_line = self.lines[item.line_no]


def load_action_items(kb_root: Path) -> list[ActionItem]:
    """Read and parse `action-items.md` from `kb_root`, tolerating a missing file.

    The one seam both the CLI entry point and the dashboard's refresh action use
    to (re-)load open action items from disk.
    """
    path = kb_root / ACTION_ITEMS_FILENAME
    if not path.is_file():
        return []
    return ActionItemsFile.parse(path.read_text(encoding="utf-8")).items
