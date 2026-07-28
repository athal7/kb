"""Alias resolution — the load-bearing entity-identity layer.

The vault's 'canonical' value in names.json / projects.json is neither the filename
nor consistently a display name:
  - "Priya Anand" -> "panand"   (canonical is the handle; file panand.md)
  - "Diego"       -> "Diego Ruiz"   (canonical is display name; file diego-ruiz.md)
So resolution unifies filename slug + H1 title + frontmatter aliases + BOTH keys and
values of the JSON tables into one registry. Every lookup returns an explicit state:
RESOLVED / AMBIGUOUS / UNRESOLVED / SUPPRESSED — never None-as-magic.
"""

import pytest

from kb.core.aliases import AliasResolver, EntityRegistry
from kb.core.models import EntityKind, EntityRef, ResolutionStatus


def _person(slug, title, aliases):
    return EntityRef(
        canonical=slug,
        kind=EntityKind.PERSON,
        file=f"people/{slug}.md",
        titles=frozenset({title}),
        aliases=frozenset(aliases),
    )


def _project(slug, title, aliases):
    return EntityRef(
        canonical=slug,
        kind=EntityKind.PROJECT,
        file=f"projects/{slug}.md",
        titles=frozenset({title}),
        aliases=frozenset(aliases),
    )


class DescribeEntityRegistry:
    def it_registers_a_person_under_slug_title_and_aliases(self):
        reg = EntityRegistry()
        ref = _person(
            "panand", "Priya Anand", ["panand", "Priya Anand", "Priya"]
        )

        reg.add(ref)

        assert reg.lookup("panand") == {ref}
        assert reg.lookup("Priya Anand") == {ref}
        assert reg.lookup("Priya") == {ref}

    def it_looks_up_case_insensitively(self):
        reg = EntityRegistry()
        ref = _person("panand", "Priya Anand", ["Priya"])
        reg.add(ref)

        assert reg.lookup("priya") == {ref}
        assert reg.lookup("PRIYA") == {ref}


class DescribeAliasResolverResolved:
    def it_resolves_a_direct_alias_to_one_entity(self):
        reg = EntityRegistry()
        priya = _person("panand", "Priya Anand", ["Priya", "Priya Anand"])
        reg.add(priya)
        resolver = AliasResolver(reg, name_table={}, project_table={})

        result = resolver.resolve("Priya", EntityKind.PERSON)

        assert result.status is ResolutionStatus.RESOLVED
        assert result.entity is priya

    def it_resolves_when_display_name_is_canonical_but_file_differs(self):
        # names.json: "Diego" -> "Diego Ruiz"; file is diego-ruiz.md.
        reg = EntityRegistry()
        diego = _person("diego-ruiz", "Diego Ruiz", ["Diego Ruiz"])
        reg.add(diego)
        resolver = AliasResolver(
            reg, name_table={"Diego": "Diego Ruiz"}, project_table={}
        )

        result = resolver.resolve("Diego", EntityKind.PERSON)

        assert result.status is ResolutionStatus.RESOLVED
        assert result.entity is diego

    def it_resolves_via_table_indirection_when_canonical_is_a_handle(self):
        # names.json: "Priya Anand" -> "panand"; file is panand.md.
        reg = EntityRegistry()
        priya = _person("panand", "Priya Anand", ["panand"])
        reg.add(priya)
        resolver = AliasResolver(
            reg, name_table={"Priya Anand": "panand"}, project_table={}
        )

        result = resolver.resolve("Priya Anand", EntityKind.PERSON)

        assert result.status is ResolutionStatus.RESOLVED
        assert result.entity is priya


class DescribeAliasResolverOtherStates:
    def it_reports_unresolved_when_nothing_matches(self):
        resolver = AliasResolver(EntityRegistry(), name_table={}, project_table={})

        result = resolver.resolve("Nobody At All", EntityKind.PERSON)

        assert result.status is ResolutionStatus.UNRESOLVED
        assert result.entity is None

    def it_reports_suppressed_when_table_maps_to_empty_string(self):
        # projects.json: "atlas-infra" -> "" means intentionally not an entity.
        resolver = AliasResolver(
            EntityRegistry(), name_table={}, project_table={"atlas-infra": ""}
        )

        result = resolver.resolve("atlas-infra", EntityKind.PROJECT)

        assert result.status is ResolutionStatus.SUPPRESSED
        assert result.entity is None

    def it_reports_ambiguous_when_multiple_entities_share_an_alias(self):
        reg = EntityRegistry()
        a = _person("marcus-webb", "Marcus Webb", ["Marcus"])
        b = _person("marcus-park", "Marcus Park", ["Marcus"])  # aliased collision on "Marcus"
        reg.add(a)
        reg.add(b)
        resolver = AliasResolver(reg, name_table={}, project_table={})

        result = resolver.resolve("Marcus", EntityKind.PERSON)

        assert result.status is ResolutionStatus.AMBIGUOUS
        assert result.entity is None
        assert result.candidates == frozenset({a, b})

    def it_uses_the_project_table_only_for_project_kind(self):
        # A project-table suppression must not leak into person resolution.
        resolver = AliasResolver(
            EntityRegistry(), name_table={}, project_table={"loki": ""}
        )

        person_result = resolver.resolve("loki", EntityKind.PERSON)
        project_result = resolver.resolve("loki", EntityKind.PROJECT)

        assert person_result.status is ResolutionStatus.UNRESOLVED
        assert project_result.status is ResolutionStatus.SUPPRESSED


class DescribeAliasResolverProductAndRepoTables:
    """product-labels.json and github-repos.json both resolve into the project domain."""

    def it_suppresses_a_generic_workflow_label(self):
        # product-labels.json: "Bug" -> "" — a generic Linear workflow label, not a project.
        resolver = AliasResolver(
            EntityRegistry(),
            name_table={},
            project_table={},
            product_label_table={"Bug": ""},
        )

        result = resolver.resolve("Bug", EntityKind.PROJECT)

        assert result.status is ResolutionStatus.SUPPRESSED
        assert result.entity is None

    def it_resolves_a_github_repo_slug_to_its_canonical_project(self):
        # github-repos.json: "lumen-prompt-toolkit" -> "lumen"; file is projects/lumen.md.
        reg = EntityRegistry()
        lumen = _project("lumen", "lumen", ["lumen"])
        reg.add(lumen)
        resolver = AliasResolver(
            reg,
            name_table={},
            project_table={},
            github_repo_table={"lumen-prompt-toolkit": "lumen"},
        )

        result = resolver.resolve("lumen-prompt-toolkit", EntityKind.PROJECT)

        assert result.status is ResolutionStatus.RESOLVED
        assert result.entity is lumen

    def it_never_resolves_the_org_metadata_key_as_an_alias(self):
        # github-repos.json: "_org" -> "lumen-labs" is org context, not an alias entry.
        resolver = AliasResolver(
            EntityRegistry(),
            name_table={},
            project_table={},
            github_repo_table={"_org": "lumen-labs", "some-repo": "Lumen"},
        )

        result = resolver.resolve("_org", EntityKind.PROJECT)

        assert result.status is ResolutionStatus.UNRESOLVED
        assert result.entity is None


@pytest.mark.parametrize("raw", ["", "   "])
def test_blank_input_is_unresolved(raw):
    resolver = AliasResolver(EntityRegistry(), name_table={}, project_table={})
    assert resolver.resolve(raw, EntityKind.PERSON).status is ResolutionStatus.UNRESOLVED
