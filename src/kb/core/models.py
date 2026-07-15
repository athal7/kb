"""Core domain dataclasses for the vault index.

Pure data — no Textual, no PyObjC, no I/O. Identity and resolution state are modeled
explicitly (ResolutionStatus) rather than leaning on None-as-magic, because unresolved
and ambiguous wikilinks are normal, expected states in a human-written vault.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from kb.core.markdown import Section


class EntityKind(enum.Enum):
    PERSON = "person"
    PROJECT = "project"
    PRODUCT = "product"


class ResolutionStatus(enum.Enum):
    RESOLVED = "resolved"       # exactly one entity matched
    AMBIGUOUS = "ambiguous"     # multiple entities matched the same reference
    UNRESOLVED = "unresolved"   # no entity matched (dead link — normal, not an error)
    SUPPRESSED = "suppressed"   # a JSON table maps this to "" — intentionally not an entity


@dataclass(frozen=True)
class EntityRef:
    """A resolvable vault entity's identity: canonical key, kind, and all its names."""

    canonical: str
    kind: EntityKind
    file: str | None = None
    titles: frozenset[str] = field(default_factory=frozenset)
    aliases: frozenset[str] = field(default_factory=frozenset)

    @property
    def all_names(self) -> frozenset[str]:
        names = {self.canonical}
        names |= set(self.titles)
        names |= set(self.aliases)
        return frozenset(names)


@dataclass(frozen=True)
class Resolution:
    """The outcome of resolving a raw reference string against the registry."""

    status: ResolutionStatus
    entity: EntityRef | None = None
    candidates: frozenset[EntityRef] = field(default_factory=frozenset)


@dataclass(frozen=True)
class Wikilink:
    raw_text: str
    source_file: str
    source_line: int
    resolution: Resolution | None = None


@dataclass
class Person:
    file: str
    frontmatter: dict
    email: str | None
    team: str | None
    title: str | None
    slack_id: str | None
    aliases: list[str]
    project_links: list[Wikilink]
    sections: list[Section]
    warnings: list[str] = field(default_factory=list)

    def section(self, heading: str) -> Section | None:
        for s in self.sections:
            if s.heading == heading:
                return s
        return None


@dataclass
class Project:
    file: str
    frontmatter: dict
    status: str | None
    product_link: Wikilink | None
    github: str | None
    linear: str | None
    aliases: list[str]
    people_links: list[Wikilink]
    sections: list[Section]
    warnings: list[str] = field(default_factory=list)

    def section(self, heading: str) -> Section | None:
        for s in self.sections:
            if s.heading == heading:
                return s
        return None


@dataclass
class Product:
    file: str
    frontmatter: dict
    status: str | None
    repos: list[str]
    linear_label: str | None
    aliases: list[str]
    sections: list[Section]
    warnings: list[str] = field(default_factory=list)


@dataclass
class JournalEntry:
    file: str
    date: str
    sections: list[Section]
    wikilinks: list[Wikilink]
    warnings: list[str] = field(default_factory=list)


@dataclass
class Decision:
    file: str
    is_readonly: bool
    sections: list[Section]
    warnings: list[str] = field(default_factory=list)
