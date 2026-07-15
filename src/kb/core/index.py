"""Wire vault parsing and alias resolution into one queryable index.

Walking the vault, parsing files, and resolving aliases are separate concerns
(parse.py, aliases.py); the UI layer needs them combined into one call: scan once,
register every person/project/product, load the four JSON lookup tables, and expose
a read-only query surface. Dangling canonicals — a table entry pointing at a name no
file registers — are recorded as build warnings rather than raised, matching the
vault's general tolerance for a single malformed entry not taking down the whole scan.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path, PurePosixPath

from kb.core.aliases import AliasResolver, EntityRegistry, _fold
from kb.core.markdown import Section
from kb.core.models import (
    Decision,
    EntityKind,
    EntityRef,
    JournalEntry,
    Person,
    Product,
    Project,
    Resolution,
    ResolutionStatus,
)
from kb.core.parse import (
    parse_decision,
    parse_journal,
    parse_person,
    parse_product,
    parse_project,
)

_SUBDIRS: dict[str, EntityKind] = {
    "people": EntityKind.PERSON,
    "projects": EntityKind.PROJECT,
    "products": EntityKind.PRODUCT,
}


def _load_json_table(path: Path) -> dict[str, str]:
    """Load a root alias table, tolerating a missing file (empty dict, no crash)."""
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _title_of(sections: list[Section]) -> str | None:
    """The H1 heading is the vault's display-name convention for an entity file."""
    for section in sections:
        if section.level == 1 and section.heading:
            return section.heading
    return None


def _canonical_of(file: str) -> str:
    return PurePosixPath(file).stem


class VaultIndex:
    """A fully-scanned, alias-resolved view of one KB vault."""

    def __init__(self) -> None:
        self._people: dict[str, Person] = {}
        self._projects: dict[str, Project] = {}
        self._products: dict[str, Product] = {}
        self._titles: dict[str, str] = {}
        self._journal: list[JournalEntry] = []
        self._decisions: list[Decision] = []
        self._registry = EntityRegistry()
        self._resolver = AliasResolver(self._registry)
        self.warnings: list[str] = []

    @classmethod
    def build(cls, kb_root: Path) -> VaultIndex:
        """Scan `kb_root` end to end: parse every file, then resolve aliases."""
        index = cls()
        index._scan(kb_root)
        index._load_alias_tables(kb_root)
        return index

    def _scan(self, kb_root: Path) -> None:
        for md_file in sorted((kb_root / "people").glob("*.md")):
            person = parse_person(
                md_file.read_text(encoding="utf-8"), file=f"people/{md_file.name}"
            )
            self._register(person, self._people, EntityKind.PERSON)

        for md_file in sorted((kb_root / "projects").glob("*.md")):
            project = parse_project(
                md_file.read_text(encoding="utf-8"), file=f"projects/{md_file.name}"
            )
            self._register(project, self._projects, EntityKind.PROJECT)

        for md_file in sorted((kb_root / "products").glob("*.md")):
            product = parse_product(
                md_file.read_text(encoding="utf-8"), file=f"products/{md_file.name}"
            )
            self._register(product, self._products, EntityKind.PRODUCT)

        for md_file in sorted((kb_root / "journal").glob("*.md")):
            self._journal.append(
                parse_journal(md_file.read_text(encoding="utf-8"), file=f"journal/{md_file.name}")
            )

        for md_file in sorted((kb_root / "decisions").glob("*.md")):
            self._decisions.append(
                parse_decision(
                    md_file.read_text(encoding="utf-8"), file=f"decisions/{md_file.name}"
                )
            )

    def _register(
        self,
        entity: Person | Project | Product,
        table: dict[str, Person | Project | Product],
        kind: EntityKind,
    ) -> None:
        canonical = _canonical_of(entity.file)
        title = _title_of(entity.sections)

        ref = EntityRef(
            canonical=canonical,
            kind=kind,
            file=entity.file,
            titles=frozenset({title}) if title else frozenset(),
            aliases=frozenset(entity.aliases),
        )
        self._registry.add(ref)
        table[canonical] = entity
        if title:
            self._titles[canonical] = title

    def _load_alias_tables(self, kb_root: Path) -> None:
        name_table = _load_json_table(kb_root / "names.json")
        project_table = _load_json_table(kb_root / "projects.json")
        product_label_table = _load_json_table(kb_root / "product-labels.json")
        github_repo_table = _load_json_table(kb_root / "github-repos.json")

        self._resolver = AliasResolver(
            self._registry,
            name_table=name_table,
            project_table=project_table,
            product_label_table=product_label_table,
            github_repo_table=github_repo_table,
        )

        self.warnings.extend(self._dangling_warnings("names.json", name_table))
        self.warnings.extend(self._dangling_warnings("projects.json", project_table))
        self.warnings.extend(
            self._dangling_warnings("product-labels.json", product_label_table)
        )
        self.warnings.extend(
            self._dangling_warnings(
                "github-repos.json", github_repo_table, skip_keys={"_org"}
            )
        )

    def _dangling_warnings(
        self, table_name: str, table: dict[str, str], skip_keys: frozenset[str] = frozenset()
    ) -> list[str]:
        warnings: list[str] = []
        for key, value in table.items():
            if key in skip_keys or not value:
                continue
            if not self._registry.lookup(value):
                warnings.append(
                    f"{table_name}: '{key}' -> '{value}' "
                    f"but no entity named '{value}' is registered"
                )
        return warnings

    # -- queries -----------------------------------------------------------

    def person(self, name: str) -> Person | None:
        return self._lookup(name, EntityKind.PERSON, self._people)

    def project(self, name: str) -> Project | None:
        return self._lookup(name, EntityKind.PROJECT, self._projects)

    def product(self, name: str) -> Product | None:
        return self._lookup(name, EntityKind.PRODUCT, self._products)

    def _lookup(self, name, kind, table):
        resolution = self.resolve_wikilink(name, kind)
        if resolution.status is not ResolutionStatus.RESOLVED:
            return None
        return table.get(resolution.entity.canonical)

    def resolve_wikilink(self, target: str, kind: EntityKind) -> Resolution:
        return self._resolver.resolve(target, kind)

    _FUZZY_CUTOFF = 0.6

    def fuzzy_matches(
        self, query: str, kinds: Iterable[EntityKind]
    ) -> list[EntityRef]:
        """Rank entities of `kinds` by how closely a known name matches `query`.

        A typo/partial-tolerant fallback for when exact/alias resolution misses:
        every registered name (canonical + H1 title + aliases) is scored with
        difflib's ratio, a substring hit counts as a strong match so `kate`
        surfaces `Kate Silverstein`, and each entity is kept once at its best
        score. Below `_FUZZY_CUTOFF` is dropped as noise. Ordered best-first.
        """
        folded = _fold(query)
        if not folded:
            return []

        wanted = set(kinds)
        scored: list[tuple[float, EntityRef]] = []
        for ref in self._registry.all_refs():
            if ref.kind not in wanted:
                continue
            best = self._best_name_score(folded, ref)
            if best >= self._FUZZY_CUTOFF:
                scored.append((best, ref))

        scored.sort(key=lambda pair: (-pair[0], self._display_key(pair[1].canonical)))
        return [ref for _, ref in scored]

    def _best_name_score(self, folded_query: str, ref: EntityRef) -> float:
        best = 0.0
        for name in ref.all_names:
            candidate = _fold(name)
            if not candidate:
                continue
            if folded_query == candidate:
                return 1.0
            ratio = SequenceMatcher(None, folded_query, candidate).ratio()
            if folded_query in candidate:
                # A clean substring (e.g. "kate" in "kate silverstein") is a
                # strong intent signal that raw ratio underweights for short
                # queries against long names — floor it, but never let it beat
                # a closer whole-name ratio elsewhere.
                ratio = max(ratio, 0.9)
            best = max(best, ratio)
        return best

    def fuzzy_people(self, query: str) -> list[EntityRef]:
        """People-scoped fuzzy search for the `/` live filter.

        Fixes the kind to PERSON so the search UI need not restate it. An empty
        query lists every person (display-sorted) so the filter has a full roster
        to show before the user types; a non-empty query defers to fuzzy_matches.
        """
        if not _fold(query):
            return [self._person_ref(k) for k in sorted(self._people, key=self._display_key)]
        return self.fuzzy_matches(query, (EntityKind.PERSON,))

    def _person_ref(self, canonical: str) -> EntityRef:
        person = self._people[canonical]
        title = self._titles.get(canonical)
        return EntityRef(
            canonical=canonical,
            kind=EntityKind.PERSON,
            file=person.file,
            titles=frozenset({title}) if title else frozenset(),
            aliases=frozenset(person.aliases),
        )

    def all_people(self) -> list[Person]:
        return [self._people[k] for k in sorted(self._people, key=self._display_key)]

    def all_projects(self) -> list[Project]:
        return [self._projects[k] for k in sorted(self._projects, key=self._display_key)]

    def all_products(self) -> list[Product]:
        return [self._products[k] for k in sorted(self._products, key=self._display_key)]

    def _display_key(self, canonical: str) -> str:
        return self._titles.get(canonical, canonical).casefold()

    def journal_entries(
        self, start: date | None = None, end: date | None = None
    ) -> list[JournalEntry]:
        entries = sorted(self._journal, key=lambda e: e.date)
        if start is None and end is None:
            return entries
        return [e for e in entries if self._in_range(e.date, start, end)]

    def _in_range(self, date_str: str, start: date | None, end: date | None) -> bool:
        try:
            parsed = date.fromisoformat(date_str)
        except ValueError:
            return False
        if start is not None and parsed < start:
            return False
        if end is not None and parsed > end:
            return False
        return True

    def decisions(self) -> list[Decision]:
        return sorted(self._decisions, key=lambda d: d.file)
