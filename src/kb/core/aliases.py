"""Entity registry and alias resolution.

The registry indexes every entity under all of its known names (canonical slug, H1
title, frontmatter aliases). The resolver layers the vault's JSON lookup tables on top:
a raw reference may resolve directly, or indirectly through a table whose value is
another known name, or be explicitly suppressed (table value ""), ambiguous, or absent.

Case-folding is applied for lookups so `[[Kate]]`, `[[kate]]`, `[[KATE]]` all resolve.
"""

from __future__ import annotations

from kb.core.models import (
    EntityKind,
    EntityRef,
    Resolution,
    ResolutionStatus,
)


def _fold(name: str) -> str:
    return name.strip().casefold()


class EntityRegistry:
    """Maps every known name (case-folded) to the set of entities bearing it."""

    def __init__(self) -> None:
        self._by_name: dict[str, set[EntityRef]] = {}

    def add(self, ref: EntityRef) -> None:
        for name in ref.all_names:
            key = _fold(name)
            if not key:
                continue
            self._by_name.setdefault(key, set()).add(ref)

    def lookup(self, name: str) -> set[EntityRef]:
        return set(self._by_name.get(_fold(name), set()))

    def all_refs(self) -> set[EntityRef]:
        """Every registered entity, once — the union across all indexed names.

        A ref appears under each of its names in `_by_name`; flattening the
        values and de-duping (EntityRef is frozen/hashable) yields one entry
        per entity, which is what fuzzy search needs to score the whole corpus.
        """
        return {ref for refs in self._by_name.values() for ref in refs}


class AliasResolver:
    """Resolves raw reference strings to an explicit Resolution state.

    The vault has four root lookup tables. Person references resolve through
    name_table alone. Project/product references can arrive via three different
    vocabularies that all describe the same canonical space — a hand-curated
    projects.json entry, a Linear label, or a GitHub repo slug — so they are merged
    into one lookup dict at construction time rather than checked in sequence on
    every call. Merge order is lowest to highest trust: github_repo_table (derived
    from repo metadata) is applied first, then product_label_table (human-assigned
    but coarse), then project_table (the hand-curated source of truth) last so it
    wins any key collision.
    """

    _ORG_METADATA_KEY = "_org"

    def __init__(
        self,
        registry: EntityRegistry,
        name_table: dict[str, str] | None = None,
        project_table: dict[str, str] | None = None,
        product_label_table: dict[str, str] | None = None,
        github_repo_table: dict[str, str] | None = None,
    ) -> None:
        self._registry = registry
        # Case-folded copies so table lookups match resolver semantics.
        self._name_table = {_fold(k): v for k, v in (name_table or {}).items()}

        github_repos = {
            k: v for k, v in (github_repo_table or {}).items() if k != self._ORG_METADATA_KEY
        }
        self._project_table: dict[str, str] = {}
        for table in (github_repos, product_label_table or {}, project_table or {}):
            self._project_table.update({_fold(k): v for k, v in table.items()})

    def _table_for(self, kind: EntityKind) -> dict[str, str]:
        return self._name_table if kind is EntityKind.PERSON else self._project_table

    def resolve(self, raw: str, kind: EntityKind) -> Resolution:
        if not raw or not raw.strip():
            return Resolution(ResolutionStatus.UNRESOLVED)

        # 1. Direct registry hit on the raw reference.
        direct = self._registry.lookup(raw)
        if len(direct) == 1:
            return Resolution(ResolutionStatus.RESOLVED, entity=next(iter(direct)))
        if len(direct) > 1:
            return Resolution(ResolutionStatus.AMBIGUOUS, candidates=frozenset(direct))

        # 2. Table indirection: raw -> canonical (or "" = suppressed) -> registry.
        table = self._table_for(kind)
        mapped = table.get(_fold(raw))
        if mapped is not None:
            if mapped == "":
                return Resolution(ResolutionStatus.SUPPRESSED)
            indirect = self._registry.lookup(mapped)
            if len(indirect) == 1:
                return Resolution(ResolutionStatus.RESOLVED, entity=next(iter(indirect)))
            if len(indirect) > 1:
                return Resolution(ResolutionStatus.AMBIGUOUS, candidates=frozenset(indirect))

        # 3. Nothing matched — a dead link is a normal, expected state.
        return Resolution(ResolutionStatus.UNRESOLVED)
