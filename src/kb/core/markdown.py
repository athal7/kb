"""Heading-agnostic markdown parsing for vault bodies.

Vault documents have no fixed section schema: journals use variant `##` headings
that change daily and frequently omit a given section entirely. This module splits
a body into an ordered list of `Section`s (whatever headings exist), extracts
checkbox items while preserving each raw line for byte-faithful editing, and finds
`[[wikilink]]` targets with their source line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_CHECKBOX = re.compile(r"^\s*- \[([ xX])\]\s?(.*)$")
_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")


@dataclass(frozen=True)
class Section:
    heading: str | None
    level: int
    lines: list[str] = field(default_factory=list)

    @property
    def body(self) -> str:
        return "\n".join(self.lines)


@dataclass(frozen=True)
class Checkbox:
    checked: bool
    text: str
    raw_line: str
    line_no: int


@dataclass(frozen=True)
class WikilinkMatch:
    raw_text: str
    line_no: int
    col: int


def split_sections(body: str) -> list[Section]:
    """Split `body` into ordered sections keyed by ATX headings.

    Text before the first heading becomes a leading section with heading=None.
    Returns [] for whitespace-only input.
    """
    if not body.strip():
        return []

    sections: list[Section] = []
    current_heading: str | None = None
    current_level = 0
    current_lines: list[str] = []
    started = False

    def flush() -> None:
        nonlocal current_lines
        # Trim trailing blank lines from each section body for stable comparisons.
        trimmed = list(current_lines)
        while trimmed and trimmed[-1] == "":
            trimmed.pop()
        sections.append(Section(current_heading, current_level, trimmed))

    for line in body.split("\n"):
        m = _HEADING.match(line)
        if m:
            if started:
                flush()
            current_heading = m.group(2)
            current_level = len(m.group(1))
            current_lines = []
            started = True
        else:
            if not started:
                # Preamble before any heading.
                started = True
                current_heading = None
                current_level = 0
            current_lines.append(line)

    if started:
        flush()

    # Drop a leading headingless section that is only blank lines.
    if sections and sections[0].heading is None and not sections[0].lines:
        sections.pop(0)

    return sections


def parse_checkboxes(body: str) -> list[Checkbox]:
    """Extract task-list checkboxes, preserving the exact raw line and 0-based line_no."""
    items: list[Checkbox] = []
    for i, line in enumerate(body.split("\n")):
        m = _CHECKBOX.match(line)
        if not m:
            continue
        checked = m.group(1) in ("x", "X")
        items.append(
            Checkbox(checked=checked, text=m.group(2), raw_line=line.rstrip("\r"), line_no=i)
        )
    return items


def find_wikilinks(body: str) -> list[WikilinkMatch]:
    """Find every `[[target]]` occurrence with its 0-based line number and column."""
    matches: list[WikilinkMatch] = []
    for i, line in enumerate(body.split("\n")):
        for m in _WIKILINK.finditer(line):
            matches.append(WikilinkMatch(raw_text=m.group(1), line_no=i, col=m.start()))
    return matches
