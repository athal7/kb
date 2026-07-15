"""VaultIndex — the single entry point that wires parsing and alias resolution
across a whole vault.

Exercised exclusively against `tests/fixtures/vault/`, never the real KB. This is the
integration seam Task B's unit tests didn't cover: alias resolution through the real
JSON tables on disk, not hand-constructed dicts.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from kb.core.index import VaultIndex
from kb.core.models import EntityKind, Person, Product, Project, ResolutionStatus

VAULT = Path(__file__).resolve().parents[1] / "fixtures" / "vault"


class DescribeBuild:
    def it_parses_every_entity_type_from_the_fixture_vault(self):
        index = VaultIndex.build(VAULT)

        assert len(index.all_people()) == 4
        assert len(index.all_projects()) == 2
        assert len(index.all_products()) == 1
        assert len(index.journal_entries()) == 2
        assert len(index.decisions()) == 2

    def it_returns_typed_model_instances(self):
        index = VaultIndex.build(VAULT)

        assert all(isinstance(p, Person) for p in index.all_people())
        assert all(isinstance(p, Project) for p in index.all_projects())
        assert all(isinstance(p, Product) for p in index.all_products())


class DescribePersonLookup:
    def it_resolves_a_display_name_through_names_json_to_the_file_backed_person(self):
        # names.json: "Stephen" -> "Stephen Golub"; file is stephen-golub.md.
        index = VaultIndex.build(VAULT)

        person = index.person("Stephen")

        assert person is not None
        assert person.file == "people/stephen-golub.md"

    def it_resolves_a_handle_through_names_json_indirection(self):
        # names.json: "Kate Silverstein" -> "ksilverstein"; file is ksilverstein.md.
        index = VaultIndex.build(VAULT)

        person = index.person("Kate Silverstein")

        assert person is not None
        assert person.file == "people/ksilverstein.md"

    def it_returns_none_for_an_unregistered_name(self):
        index = VaultIndex.build(VAULT)

        assert index.person("Nobody At All") is None


class DescribeProjectLookup:
    def it_resolves_a_projects_json_alias_to_the_file_backed_project(self):
        # projects.json: "odin-firewall" -> "Firewall"; file is projects/firewall.md.
        index = VaultIndex.build(VAULT)

        project = index.project("odin-firewall")

        assert project is not None
        assert project.file == "projects/firewall.md"

    def it_resolves_a_github_repo_slug_through_github_repos_json(self):
        # github-repos.json: "repo-slug" -> "0DIN"; file is products/0din.md.
        index = VaultIndex.build(VAULT)

        product = index.product("repo-slug")

        assert product is not None
        assert product.file == "products/0din.md"


class DescribeBuildWarnings:
    def it_flags_a_dangling_canonical_in_projects_json(self):
        # projects.json: "legacy-name" -> "Ghost Project", which no file registers.
        index = VaultIndex.build(VAULT)

        assert any("legacy-name" in w and "Ghost Project" in w for w in index.warnings)

    def it_does_not_flag_a_suppression_as_dangling(self):
        index = VaultIndex.build(VAULT)

        assert not any("webservices-infra" in w for w in index.warnings)


class DescribeJournalEntries:
    def it_returns_entries_sorted_by_date(self):
        index = VaultIndex.build(VAULT)

        entries = index.journal_entries()

        assert [e.date for e in entries] == ["2026-07-12", "2026-07-13"]

    def it_filters_by_date_range(self):
        index = VaultIndex.build(VAULT)

        entries = index.journal_entries(start=date(2026, 7, 13), end=date(2026, 7, 13))

        assert [e.date for e in entries] == ["2026-07-13"]


class DescribeMissingAliasTables:
    def it_does_not_crash_when_alias_tables_are_absent(self, tmp_path):
        for sub in ("people", "projects", "products", "journal", "decisions"):
            (tmp_path / sub).mkdir()
        (tmp_path / "people" / "solo.md").write_text("# Solo\n")

        index = VaultIndex.build(tmp_path)

        assert index.warnings == []
        assert index.person("Solo") is not None


class DescribeResolveWikilink:
    def it_delegates_to_the_alias_resolver(self):
        index = VaultIndex.build(VAULT)

        result = index.resolve_wikilink("Kate", EntityKind.PERSON)

        assert result.status is ResolutionStatus.RESOLVED
        assert result.entity.file == "people/ksilverstein.md"
