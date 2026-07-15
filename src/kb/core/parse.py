"""Turn raw vault files into domain models.

This layer sits on top of `frontmatter.split` and `markdown.split_sections`/
`find_wikilinks`. It absorbs the vault's real-world drift so nothing downstream has to:

  - `slack:` vs `slack_id:` — the SKILL doc documents `slack`, real files use `slack_id`.
    Both land in one `slack_id` field, preferring the explicit `slack_id` when both exist.
  - Frontmatter may be entirely absent (journal, decisions) — parsing never raises.
  - Frontmatter list fields hold wikilink strings (`"[[Kate]]"`) that are unwrapped to
    raw targets for later resolution, tolerating stray brackets/whitespace.
  - Journals have no fixed heading schema and no frontmatter; the H1 date is the identity,
    with the filename date as a fallback.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from kb.core.frontmatter import split
from kb.core.markdown import find_wikilinks, split_sections
from kb.core.models import (
    Decision,
    JournalEntry,
    Person,
    Product,
    Project,
    Wikilink,
)

_WIKILINK_WRAP = re.compile(r"^\s*\[\[\s*(.*?)\s*\]\]\s*$")
_H1_DATE = re.compile(r"^#\s+(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)
_FILENAME_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _unwrap_wikilink(value: object) -> str | None:
    """Extract the target from a `"[[Target]]"` frontmatter entry.

    Tolerates missing brackets and surrounding whitespace. Returns None for empty values.
    """
    if not isinstance(value, str):
        return None
    m = _WIKILINK_WRAP.match(value)
    target = m.group(1) if m else value.strip()
    return target or None


def _wikilinks_from_frontmatter(fm: dict, key: str, file: str) -> list[Wikilink]:
    """Build wikilinks from a frontmatter list field of `"[[X]]"` strings."""
    raw = fm.get(key)
    if not isinstance(raw, list):
        return []
    links: list[Wikilink] = []
    for entry in raw:
        target = _unwrap_wikilink(entry)
        if target is not None:
            links.append(Wikilink(raw_text=target, source_file=file, source_line=0))
    return links


def _wikilink_from_frontmatter(fm: dict, key: str, file: str) -> Wikilink | None:
    """Build a single wikilink from a scalar frontmatter field like `product: "[[X]]"`."""
    target = _unwrap_wikilink(fm.get(key))
    if target is None:
        return None
    return Wikilink(raw_text=target, source_file=file, source_line=0)


def _aliases(fm: dict) -> list[str]:
    raw = fm.get("aliases")
    if not isinstance(raw, list):
        return []
    return [str(a) for a in raw if isinstance(a, str)]


def _str_or_none(fm: dict, key: str) -> str | None:
    value = fm.get(key)
    return str(value) if value is not None else None


def parse_person(text: str, *, file: str) -> Person:
    result = split(text)
    fm = result.frontmatter or {}
    warnings = [result.warning] if result.warning else []

    # slack_id drift: explicit slack_id wins, else fall back to documented `slack`.
    slack_id = _str_or_none(fm, "slack_id") or _str_or_none(fm, "slack")

    return Person(
        file=file,
        frontmatter=fm,
        email=_str_or_none(fm, "email"),
        team=_str_or_none(fm, "team"),
        title=_str_or_none(fm, "title"),
        slack_id=slack_id,
        aliases=_aliases(fm),
        project_links=_wikilinks_from_frontmatter(fm, "projects", file),
        sections=split_sections(result.body),
        warnings=warnings,
    )


def parse_project(text: str, *, file: str) -> Project:
    result = split(text)
    fm = result.frontmatter or {}
    warnings = [result.warning] if result.warning else []

    return Project(
        file=file,
        frontmatter=fm,
        status=_str_or_none(fm, "status"),
        product_link=_wikilink_from_frontmatter(fm, "product", file),
        github=_str_or_none(fm, "github"),
        linear=_str_or_none(fm, "linear"),
        aliases=_aliases(fm),
        people_links=_wikilinks_from_frontmatter(fm, "people", file),
        sections=split_sections(result.body),
        warnings=warnings,
    )


def parse_product(text: str, *, file: str) -> Product:
    result = split(text)
    fm = result.frontmatter or {}
    warnings = [result.warning] if result.warning else []

    repos_raw = fm.get("repos")
    repos = [str(r) for r in repos_raw] if isinstance(repos_raw, list) else []

    return Product(
        file=file,
        frontmatter=fm,
        status=_str_or_none(fm, "status"),
        repos=repos,
        linear_label=_str_or_none(fm, "linear"),
        aliases=_aliases(fm),
        sections=split_sections(result.body),
        warnings=warnings,
    )


def _journal_date(body: str, file: str) -> str:
    """Prefer the H1 `# YYYY-MM-DD` heading; fall back to the filename date."""
    m = _H1_DATE.search(body)
    if m:
        return m.group(1)
    stem = PurePosixPath(file).stem
    fm = _FILENAME_DATE.search(stem)
    return fm.group(1) if fm else stem


def _strip_h1_date(body: str) -> str:
    """Drop the leading `# YYYY-MM-DD` identity heading so only content sections remain."""
    lines = body.split("\n")
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if _H1_DATE.match(line):
            return "\n".join(lines[i + 1 :])
        break
    return body


def parse_journal(text: str, *, file: str) -> JournalEntry:
    result = split(text)
    warnings = [result.warning] if result.warning else []
    # Journals have no frontmatter; if a stray block was split off, keep working on body.
    body = result.body
    date = _journal_date(body, file)

    # Wikilinks are collected across the whole body (line numbers stay true to the file);
    # only the section split drops the H1 date heading, which is identity, not content.
    wikilinks = [
        Wikilink(raw_text=w.raw_text, source_file=file, source_line=w.line_no)
        for w in find_wikilinks(body)
    ]

    return JournalEntry(
        file=file,
        date=date,
        sections=split_sections(_strip_h1_date(body)),
        wikilinks=wikilinks,
        warnings=warnings,
    )


def parse_decision(text: str, *, file: str) -> Decision:
    result = split(text)
    warnings = [result.warning] if result.warning else []
    is_readonly = PurePosixPath(file).name == "archive.md"

    return Decision(
        file=file,
        is_readonly=is_readonly,
        sections=split_sections(result.body),
        warnings=warnings,
    )
