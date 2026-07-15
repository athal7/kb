"""Alias resolution — the load-bearing entity-identity layer.

The vault's 'canonical' value in names.json / projects.json is neither the filename
nor consistently a display name:
  - "Kate Silverstein" -> "ksilverstein"   (canonical is the handle; file ksilverstein.md)
  - "Stephen"          -> "Stephen Golub"   (canonical is display name; file stephen-golub.md)
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
            "ksilverstein", "Kate Silverstein", ["ksilverstein", "Kate Silverstein", "Kate"]
        )

        reg.add(ref)

        assert reg.lookup("ksilverstein") == {ref}
        assert reg.lookup("Kate Silverstein") == {ref}
        assert reg.lookup("Kate") == {ref}

    def it_looks_up_case_insensitively(self):
        reg = EntityRegistry()
        ref = _person("ksilverstein", "Kate Silverstein", ["Kate"])
        reg.add(ref)

        assert reg.lookup("kate") == {ref}
        assert reg.lookup("KATE") == {ref}


class DescribeAliasResolverResolved:
    def it_resolves_a_direct_alias_to_one_entity(self):
        reg = EntityRegistry()
        kate = _person("ksilverstein", "Kate Silverstein", ["Kate", "Kate Silverstein"])
        reg.add(kate)
        resolver = AliasResolver(reg, name_table={}, project_table={})

        result = resolver.resolve("Kate", EntityKind.PERSON)

        assert result.status is ResolutionStatus.RESOLVED
        assert result.entity is kate

    def it_resolves_when_display_name_is_canonical_but_file_differs(self):
        # names.json: "Stephen" -> "Stephen Golub"; file is stephen-golub.md.
        reg = EntityRegistry()
        stephen = _person("stephen-golub", "Stephen Golub", ["Stephen Golub"])
        reg.add(stephen)
        resolver = AliasResolver(
            reg, name_table={"Stephen": "Stephen Golub"}, project_table={}
        )

        result = resolver.resolve("Stephen", EntityKind.PERSON)

        assert result.status is ResolutionStatus.RESOLVED
        assert result.entity is stephen

    def it_resolves_via_table_indirection_when_canonical_is_a_handle(self):
        # names.json: "Kate Silverstein" -> "ksilverstein"; file is ksilverstein.md.
        reg = EntityRegistry()
        kate = _person("ksilverstein", "Kate Silverstein", ["ksilverstein"])
        reg.add(kate)
        resolver = AliasResolver(
            reg, name_table={"Kate Silverstein": "ksilverstein"}, project_table={}
        )

        result = resolver.resolve("Kate Silverstein", EntityKind.PERSON)

        assert result.status is ResolutionStatus.RESOLVED
        assert result.entity is kate


class DescribeAliasResolverOtherStates:
    def it_reports_unresolved_when_nothing_matches(self):
        resolver = AliasResolver(EntityRegistry(), name_table={}, project_table={})

        result = resolver.resolve("Nobody At All", EntityKind.PERSON)

        assert result.status is ResolutionStatus.UNRESOLVED
        assert result.entity is None

    def it_reports_suppressed_when_table_maps_to_empty_string(self):
        # projects.json: "webservices-infra" -> "" means intentionally not an entity.
        resolver = AliasResolver(
            EntityRegistry(), name_table={}, project_table={"webservices-infra": ""}
        )

        result = resolver.resolve("webservices-infra", EntityKind.PROJECT)

        assert result.status is ResolutionStatus.SUPPRESSED
        assert result.entity is None

    def it_reports_ambiguous_when_multiple_entities_share_an_alias(self):
        reg = EntityRegistry()
        a = _person("andrew-thal", "Andrew Thal", ["Andrew"])
        b = _person("andre", "Andre", ["Andrew"])  # aliased collision on "Andrew"
        reg.add(a)
        reg.add(b)
        resolver = AliasResolver(reg, name_table={}, project_table={})

        result = resolver.resolve("Andrew", EntityKind.PERSON)

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
        # github-repos.json: "0din-prompt-toolkit" -> "0din"; file is projects/0din.md.
        reg = EntityRegistry()
        odin = _project("0din", "0din", ["0din"])
        reg.add(odin)
        resolver = AliasResolver(
            reg,
            name_table={},
            project_table={},
            github_repo_table={"0din-prompt-toolkit": "0din"},
        )

        result = resolver.resolve("0din-prompt-toolkit", EntityKind.PROJECT)

        assert result.status is ResolutionStatus.RESOLVED
        assert result.entity is odin

    def it_never_resolves_the_org_metadata_key_as_an_alias(self):
        # github-repos.json: "_org" -> "0din-ai" is org context, not an alias entry.
        resolver = AliasResolver(
            EntityRegistry(),
            name_table={},
            project_table={},
            github_repo_table={"_org": "0din-ai", "some-repo": "Odin"},
        )

        result = resolver.resolve("_org", EntityKind.PROJECT)

        assert result.status is ResolutionStatus.UNRESOLVED
        assert result.entity is None


@pytest.mark.parametrize("raw", ["", "   "])
def test_blank_input_is_unresolved(raw):
    resolver = AliasResolver(EntityRegistry(), name_table={}, project_table={})
    assert resolver.resolve(raw, EntityKind.PERSON).status is ResolutionStatus.UNRESOLVED
