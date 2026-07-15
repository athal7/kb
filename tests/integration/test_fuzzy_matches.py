"""VaultIndex.fuzzy_matches — typo/partial-tolerant entity search.

A fallback for when exact/alias resolution misses: rank every registered entity
by how closely its known names (canonical + H1 title + frontmatter aliases)
match the query. Exercised against the fixture vault so aliases from real
frontmatter and names.json indirection are in play, not hand-built dicts.
"""

from __future__ import annotations

from pathlib import Path

from kb.core.index import VaultIndex
from kb.core.models import EntityKind, EntityRef

VAULT = Path(__file__).resolve().parents[1] / "fixtures" / "vault"


def _display(ref: EntityRef) -> str:
    return sorted(ref.titles)[0] if ref.titles else ref.canonical


class DescribeFuzzyMatches:
    def it_surfaces_a_person_from_a_typo(self):
        index = VaultIndex.build(VAULT)

        matches = index.fuzzy_matches("andrw", (EntityKind.PERSON,))

        assert matches
        assert _display(matches[0]) == "Andrew Thal"

    def it_surfaces_a_person_from_a_partial_name(self):
        index = VaultIndex.build(VAULT)

        matches = index.fuzzy_matches("silverstien", (EntityKind.PERSON,))

        assert matches
        assert _display(matches[0]) == "Kate Silverstein"

    def it_matches_against_frontmatter_aliases_not_just_the_display_name(self):
        # stephen-golub.md has alias "Stephen"; a typo of the alias should still
        # surface the canonical entity, proving all-names (not just title) matching.
        index = VaultIndex.build(VAULT)

        matches = index.fuzzy_matches("stephn", (EntityKind.PERSON,))

        assert matches
        assert _display(matches[0]) == "Stephen Golub"

    def it_returns_empty_for_a_query_that_resembles_nothing(self):
        index = VaultIndex.build(VAULT)

        assert index.fuzzy_matches("zzzzxqptw", (EntityKind.PERSON,)) == []

    def it_dedupes_to_one_ref_per_entity(self):
        # Kate has three names (ksilverstein, Kate Silverstein, Kate); a query
        # that fuzzily hits more than one of them must still yield her once.
        index = VaultIndex.build(VAULT)

        matches = index.fuzzy_matches("kate silverstein", (EntityKind.PERSON,))

        kate_hits = [m for m in matches if m.canonical == "ksilverstein"]
        assert len(kate_hits) == 1

    def it_ranks_the_closest_name_first(self):
        index = VaultIndex.build(VAULT)

        matches = index.fuzzy_matches("andrew", (EntityKind.PERSON,))

        assert _display(matches[0]) == "Andrew Thal"

    def it_searches_all_requested_kinds(self):
        index = VaultIndex.build(VAULT)

        kinds = (EntityKind.PERSON, EntityKind.PROJECT, EntityKind.PRODUCT)
        project_match = index.fuzzy_matches("firewal", kinds)
        product_match = index.fuzzy_matches("0di", kinds)

        assert any(m.kind is EntityKind.PROJECT for m in project_match)
        assert any(m.kind is EntityKind.PRODUCT for m in product_match)

    def it_only_returns_refs_of_the_requested_kinds(self):
        index = VaultIndex.build(VAULT)

        matches = index.fuzzy_matches("firewal", (EntityKind.PERSON,))

        assert all(m.kind is EntityKind.PERSON for m in matches)


class DescribeFuzzyPeople:
    """fuzzy_people is the people-scoped convenience over fuzzy_matches used by
    the `/` live-filter search — it fixes kind to PERSON and, on an empty query,
    lists everyone so the search UI has something to show before a key is typed."""

    def it_ranks_the_closest_person_first(self):
        index = VaultIndex.build(VAULT)

        matches = index.fuzzy_people("silverstien")

        assert matches
        assert _display(matches[0]) == "Kate Silverstein"

    def it_matches_against_frontmatter_aliases(self):
        # "sgolub" is only reachable via an alias, never the display name.
        index = VaultIndex.build(VAULT)

        matches = index.fuzzy_people("stephn")

        assert matches
        assert _display(matches[0]) == "Stephen Golub"

    def it_only_returns_people(self):
        index = VaultIndex.build(VAULT)

        # "firewal" is a project; scoped-to-people search must not surface it.
        matches = index.fuzzy_people("firewal")

        assert all(m.kind is EntityKind.PERSON for m in matches)

    def it_lists_every_person_for_an_empty_query(self):
        index = VaultIndex.build(VAULT)

        matches = index.fuzzy_people("")

        assert {m.kind for m in matches} == {EntityKind.PERSON}
        assert len(matches) == len(index.all_people())

    def it_returns_empty_for_a_query_that_resembles_nothing(self):
        index = VaultIndex.build(VAULT)

        assert index.fuzzy_people("zzzzxqptw") == []
