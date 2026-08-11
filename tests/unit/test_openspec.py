"""Unit tests for src/kb/core/openspec.py — archive discovery, parsing, and querying.

Fixtures live in tests/fixtures/openspec/ and mirror the real layout at
~/.local/share/kb/openspec/<repo-slug>/.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from kb.core.openspec import (
    AmbiguousChangeError,
    OpenSpecStore,
    parse_kb_meta,
    read_design_md,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "openspec"


# ---------------------------------------------------------------------------
# parse_kb_meta
# ---------------------------------------------------------------------------

class DescribeParseKbMeta:
    def it_parses_a_valid_kb_meta_yaml(self):
        meta_file = FIXTURES / "alpha-repo" / "changes" / "archive" / "2026-03-15-add-auth-flow" / "kb-meta.yaml"
        result = parse_kb_meta(meta_file)

        assert result is not None
        assert result["worktree"] == "/tmp/fake-worktrees/alpha-repo"
        assert result["branch"] == "feature/add-auth-flow"
        assert result["date"] == "2026-03-15"
        assert result["change"] == "add-auth-flow"

    def it_returns_none_for_missing_file(self):
        result = parse_kb_meta(Path("/nonexistent/kb-meta.yaml"))
        assert result is None

    def it_returns_none_for_malformed_yaml(self, tmp_path):
        bad_yaml = tmp_path / "kb-meta.yaml"
        bad_yaml.write_text("key: [unclosed", encoding="utf-8")
        result = parse_kb_meta(bad_yaml)
        assert result is None


# ---------------------------------------------------------------------------
# read_design_md
# ---------------------------------------------------------------------------

class DescribeReadDesignMd:
    def it_returns_the_full_text_of_design_md(self):
        design_file = FIXTURES / "alpha-repo" / "changes" / "archive" / "2026-03-15-add-auth-flow" / "design.md"
        result = read_design_md(design_file)

        assert result is not None
        assert "# Add Authentication Flow" in result
        assert "## Context" in result

    def it_returns_none_for_missing_file(self):
        result = read_design_md(Path("/nonexistent/design.md"))
        assert result is None


# ---------------------------------------------------------------------------
# OpenSpecStore — discovery and listing
# ---------------------------------------------------------------------------

class DescribeOpenSpecStore:
    def setup_method(self):
        self.store = OpenSpecStore(FIXTURES)

    def it_discovers_all_repo_slugs(self):
        repos = self.store.repo_slugs()
        assert set(repos) == {"alpha-repo", "beta-project"}

    def it_lists_all_archives(self):
        archives = self.store.list_archives()
        assert len(archives) == 5

        # Check structure
        for entry in archives:
            assert "worktree" in entry
            assert "branch" in entry
            assert "date" in entry
            assert "change" in entry
            assert "repo" in entry
            assert "path" in entry

    def it_lists_archives_sorted_by_date_descending(self):
        archives = self.store.list_archives()
        dates = [a["date"] for a in archives]
        assert dates == sorted(dates, reverse=True)

    def it_filters_archives_by_repo(self):
        alpha_archives = self.store.list_archives(repo="alpha-repo")
        assert len(alpha_archives) == 3
        assert all(a["repo"] == "alpha-repo" for a in alpha_archives)

        beta_archives = self.store.list_archives(repo="beta-project")
        assert len(beta_archives) == 2
        assert all(a["repo"] == "beta-project" for a in beta_archives)

    def it_filters_archives_by_date_range(self):
        jan = self.store.list_archives(from_date="2026-01-01", to_date="2026-01-31")
        assert len(jan) == 1
        assert jan[0]["date"] == "2026-01-20"

    def it_filters_archives_by_date_range_exclusive(self):
        march = self.store.list_archives(from_date="2026-03-01", to_date="2026-03-31")
        assert len(march) == 1
        assert march[0]["date"] == "2026-03-15"

    def it_filters_archives_by_combined_repo_and_date(self):
        result = self.store.list_archives(repo="alpha-repo", from_date="2026-03-01", to_date="2026-03-31")
        assert len(result) == 1
        assert result[0]["change"] == "add-auth-flow"

    def it_returns_empty_list_for_no_matches(self):
        result = self.store.list_archives(from_date="2099-01-01", to_date="2099-12-31")
        assert result == []

    def it_returns_empty_list_for_unknown_repo(self):
        result = self.store.list_archives(repo="nonexistent")
        assert result == []

    def it_returns_empty_list_for_unknown_repo_with_date(self):
        result = self.store.list_archives(repo="nonexistent", from_date="2026-01-01", to_date="2026-12-31")
        assert result == []

    def it_excludes_entry_with_missing_date_when_from_filter_applied(self):
        result = self.store.list_archives(from_date="2026-01-01")
        no_date_entries = [e for e in result if e["change"] == "no-date-change"]
        assert len(no_date_entries) == 0

    def it_excludes_entry_with_missing_date_when_to_filter_applied(self):
        result = self.store.list_archives(to_date="2026-12-31")
        no_date_entries = [e for e in result if e["change"] == "no-date-change"]
        assert len(no_date_entries) == 0

    def it_excludes_entry_with_missing_date_when_both_filters_applied(self):
        result = self.store.list_archives(from_date="2026-01-01", to_date="2026-12-31")
        no_date_entries = [e for e in result if e["change"] == "no-date-change"]
        assert len(no_date_entries) == 0

    def it_includes_entry_with_missing_date_when_no_date_filter(self):
        result = self.store.list_archives()
        no_date_entries = [e for e in result if e["change"] == "no-date-change"]
        assert len(no_date_entries) == 1
        assert no_date_entries[0]["date"] == ""

    def it_excludes_entry_with_empty_date_when_from_filter_applied(self, tmp_path):
        store = OpenSpecStore(tmp_path)
        repo_dir = tmp_path / "test-repo" / "changes" / "archive"
        repo_dir.mkdir(parents=True)
        entry_dir = repo_dir / "2026-01-01-empty-date"
        entry_dir.mkdir()
        (entry_dir / "kb-meta.yaml").write_text(
            "worktree: /tmp/w\nbranch: main\ndate: ''\nchange: empty-date\n",
            encoding="utf-8",
        )
        (entry_dir / "design.md").write_text("# Empty date", encoding="utf-8")
        result = store.list_archives(from_date="2026-01-01")
        empty_date_entries = [e for e in result if e["change"] == "empty-date"]
        assert len(empty_date_entries) == 0

    def it_excludes_entry_with_unparseable_date_when_from_filter_applied(self, tmp_path):
        store = OpenSpecStore(tmp_path)
        repo_dir = tmp_path / "test-repo" / "changes" / "archive"
        repo_dir.mkdir(parents=True)
        entry_dir = repo_dir / "2026-01-01-bad-date"
        entry_dir.mkdir()
        (entry_dir / "kb-meta.yaml").write_text(
            "worktree: /tmp/w\nbranch: main\ndate: not-a-date\nchange: bad-date\n",
            encoding="utf-8",
        )
        (entry_dir / "design.md").write_text("# Bad date", encoding="utf-8")
        result = store.list_archives(from_date="2026-01-01")
        bad_date_entries = [e for e in result if e["change"] == "bad-date"]
        assert len(bad_date_entries) == 0


# ---------------------------------------------------------------------------
# OpenSpecStore — show archive
# ---------------------------------------------------------------------------

class DescribeOpenSpecStoreShowArchive:
    def setup_method(self):
        self.store = OpenSpecStore(FIXTURES)

    def it_raises_ambiguous_change_error_for_ambiguous_change_name(self):
        with pytest.raises(AmbiguousChangeError):
            self.store.show_archive("add-auth-flow")

    def it_finds_archive_by_change_name_with_repo_scope(self):
        result = self.store.show_archive("add-auth-flow", repo="alpha-repo")
        assert result is not None
        assert result["meta"]["change"] == "add-auth-flow"
        assert result["meta"]["repo"] == "alpha-repo"
        assert "Add Authentication Flow" in result["design"]

    def it_finds_archive_by_change_name_in_other_repo(self):
        result = self.store.show_archive("refactor-api")
        assert result is not None
        assert result["meta"]["change"] == "refactor-api"
        assert result["meta"]["repo"] == "beta-project"

    def it_returns_none_for_unknown_change(self):
        result = self.store.show_archive("nonexistent-change")
        assert result is None

    def it_handles_change_name_collision_with_repo_flag(self):
        result = self.store.show_archive("add-auth-flow", repo="alpha-repo")
        assert result is not None
        assert result["meta"]["repo"] == "alpha-repo"

    def it_includes_design_content(self):
        result = self.store.show_archive("add-auth-flow", repo="alpha-repo")
        assert result["design"] is not None
        assert "## Context" in result["design"]
        assert "## Decisions" in result["design"]


# ---------------------------------------------------------------------------
# OpenSpecStore — standing specs
# ---------------------------------------------------------------------------

class DescribeOpenSpecStoreSpecs:
    def setup_method(self):
        self.store = OpenSpecStore(FIXTURES)

    def it_lists_all_standing_specs(self):
        specs = self.store.list_specs()
        assert len(specs) == 3

        for spec in specs:
            assert "repo" in spec
            assert "name" in spec
            assert "path" in spec

    def it_lists_specs_for_a_specific_repo(self):
        alpha_specs = self.store.list_specs(repo="alpha-repo")
        assert len(alpha_specs) == 2
        assert all(s["repo"] == "alpha-repo" for s in alpha_specs)

        beta_specs = self.store.list_specs(repo="beta-project")
        assert len(beta_specs) == 1
        assert beta_specs[0]["repo"] == "beta-project"

    def it_returns_empty_list_for_unknown_repo(self):
        result = self.store.list_specs(repo="nonexistent")
        assert result == []

    def it_shows_a_standing_spec(self):
        result = self.store.show_spec("auth-flow", repo="alpha-repo")
        assert result is not None
        assert result["repo"] == "alpha-repo"
        assert result["name"] == "auth-flow"
        assert "auth-flow Specification" in result["content"]

    def it_shows_a_standing_spec_in_other_repo(self):
        result = self.store.show_spec("api-contract", repo="beta-project")
        assert result is not None
        assert result["name"] == "api-contract"
        assert "api-contract Specification" in result["content"]

    def it_returns_none_for_unknown_spec(self):
        result = self.store.show_spec("nonexistent-spec", repo="alpha-repo")
        assert result is None

    def it_returns_none_for_spec_in_unknown_repo(self):
        result = self.store.show_spec("auth-flow", repo="nonexistent")
        assert result is None
