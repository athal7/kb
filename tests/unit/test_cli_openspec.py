"""CLI integration tests for `kb openspec` command group.

Uses CliRunner to drive the click Group directly against the openspec fixture
data in tests/fixtures/openspec/.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from kb.__main__ import cli

OPENSPEC_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "openspec"


class DescribeOpenspecList:
    def it_prints_all_archives_as_json_array(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(cli, ["openspec", "list"])

        assert result.exit_code == 0
        archives = json.loads(result.output)
        assert isinstance(archives, list)
        assert len(archives) == 5

        # Check structure
        for entry in archives:
            assert "worktree" in entry
            assert "branch" in entry
            assert "date" in entry
            assert "change" in entry
            assert "repo" in entry

    def it_sorts_by_date_descending(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(cli, ["openspec", "list"])

        assert result.exit_code == 0
        archives = json.loads(result.output)
        dates = [a["date"] for a in archives]
        assert dates == sorted(dates, reverse=True)

    def it_filters_by_repo(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(cli, ["openspec", "list", "--repo", "alpha-repo"])

        assert result.exit_code == 0
        archives = json.loads(result.output)
        assert len(archives) == 3
        assert all(a["repo"] == "alpha-repo" for a in archives)

        result = CliRunner().invoke(cli, ["openspec", "list", "--repo", "beta-project"])

        assert result.exit_code == 0
        archives = json.loads(result.output)
        assert len(archives) == 2
        assert all(a["repo"] == "beta-project" for a in archives)

    def it_filters_by_date_range(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(cli, [
            "openspec", "list",
            "--from", "2026-01-01",
            "--to", "2026-01-31"
        ])

        assert result.exit_code == 0
        archives = json.loads(result.output)
        assert len(archives) == 1
        assert archives[0]["date"] == "2026-01-20"

    def it_filters_by_combined_repo_and_date(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(cli, [
            "openspec", "list",
            "--repo", "alpha-repo",
            "--from", "2026-03-01",
            "--to", "2026-03-31"
        ])

        assert result.exit_code == 0
        archives = json.loads(result.output)
        assert len(archives) == 1
        assert archives[0]["change"] == "add-auth-flow"

    def it_returns_empty_array_for_no_matches(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(cli, [
            "openspec", "list",
            "--from", "2099-01-01",
            "--to", "2099-12-31"
        ])

        assert result.exit_code == 0
        assert json.loads(result.output) == []

    def it_rejects_invalid_from_date(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(cli, ["openspec", "list", "--from", "not-a-date"])

        assert result.exit_code != 0
        assert "must be in YYYY-MM-DD format" in result.output

    def it_rejects_invalid_to_date(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(cli, ["openspec", "list", "--to", "not-a-date"])

        assert result.exit_code != 0
        assert "must be in YYYY-MM-DD format" in result.output

    def it_rejects_malformed_date(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(cli, ["openspec", "list", "--from", "2026/01/01"])

        assert result.exit_code != 0
        assert "must be in YYYY-MM-DD format" in result.output


class DescribeOpenspecShow:
    def it_prints_archive_metadata_and_design_as_json(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(cli, ["openspec", "show", "add-auth-flow", "--repo", "alpha-repo"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "meta" in data
        assert "design" in data
        assert data["meta"]["change"] == "add-auth-flow"
        assert data["meta"]["repo"] == "alpha-repo"
        assert "Add Authentication Flow" in data["design"]

    def it_exits_non_zero_for_ambiguous_change_name(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(cli, ["openspec", "show", "add-auth-flow"])

        assert result.exit_code != 0
        error_data = json.loads(result.output)
        assert error_data["error"] == "ambiguous"
        assert error_data["change"] == "add-auth-flow"

    def it_prints_archive_from_other_repo(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(cli, ["openspec", "show", "refactor-api"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["meta"]["change"] == "refactor-api"
        assert data["meta"]["repo"] == "beta-project"

    def it_exits_non_zero_for_unknown_change(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(cli, ["openspec", "show", "nonexistent-change"])

        assert result.exit_code != 0
        assert "not found" in (result.output + str(result.exception)).lower()


class DescribeOpenspecSpecsList:
    def it_prints_all_standing_specs_as_json_array(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(cli, ["openspec", "specs", "list"])

        assert result.exit_code == 0
        specs = json.loads(result.output)
        assert isinstance(specs, list)
        assert len(specs) == 3

        for spec in specs:
            assert "repo" in spec
            assert "name" in spec
            assert "path" in spec

    def it_filters_standing_specs_by_repo(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(cli, ["openspec", "specs", "list", "--repo", "alpha-repo"])

        assert result.exit_code == 0
        specs = json.loads(result.output)
        assert len(specs) == 2
        assert all(s["repo"] == "alpha-repo" for s in specs)


class DescribeOpenspecSpecsShow:
    def it_prints_standing_spec_content_as_json(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(cli, [
            "openspec", "specs", "show", "auth-flow", "--repo", "alpha-repo"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "repo" in data
        assert data["repo"] == "alpha-repo"
        assert "name" in data
        assert data["name"] == "auth-flow"
        assert "content" in data
        assert "auth-flow Specification" in data["content"]

    def it_prints_standing_spec_from_other_repo(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(cli, [
            "openspec", "specs", "show", "api-contract", "--repo", "beta-project"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["name"] == "api-contract"
        assert "api-contract Specification" in data["content"]

    def it_exits_non_zero_for_unknown_spec(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(cli, [
            "openspec", "specs", "show", "nonexistent-spec", "--repo", "alpha-repo"
        ])

        assert result.exit_code != 0
        assert "not found" in (result.output + str(result.exception)).lower()


def _initialize_git_repository(path: Path) -> None:
    subprocess.run(
        ["git", "init", "--initial-branch=main"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


class DescribeOpenspecImport:
    def it_imports_an_approved_plan_record(self, monkeypatch, tmp_path):
        worktree = tmp_path / "example-repo"
        worktree.mkdir()
        _initialize_git_repository(worktree)
        plan_content = "# Import CLI Plan\n\n## Context\nStore this plan."
        record = {
            "session_id": "session-cli",
            "worktree": str(worktree),
            "approval_time": "2026-08-18T10:30:00+00:00",
            "plan_content": plan_content,
            "plan_sha256": hashlib.sha256(plan_content.encode("utf-8")).hexdigest(),
            "verified_implementation_evidence": "Focused tests passed.",
        }
        record_path = tmp_path / "record.json"
        record_path.write_text(json.dumps(record), encoding="utf-8")
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(tmp_path / "openspec"))

        result = CliRunner().invoke(cli, ["openspec", "import", str(record_path)])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["repo"] == "example-repo"
        assert data["change"] == "import-cli-plan"
        assert data["created"] is True

    def it_returns_a_json_error_for_malformed_records(self, monkeypatch, tmp_path):
        record_path = tmp_path / "record.json"
        record_path.write_text("{", encoding="utf-8")
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(tmp_path / "openspec"))

        result = CliRunner().invoke(cli, ["openspec", "import", str(record_path)])

        assert result.exit_code != 0
        assert json.loads(result.output)["error"]["code"] == "invalid_record"


class DescribeOpenspecFormat:
    def it_lists_archives_as_text_when_format_text_is_specified(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(
            cli, ["--format", "text", "openspec", "list", "--repo", "alpha-repo"]
        )

        assert result.exit_code == 0
        assert "Change: add-auth-flow" in result.output
        assert "Repo: alpha-repo" in result.output

    def it_shows_archive_metadata_and_design_as_text(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(
            cli,
            ["--format", "text", "openspec", "show", "add-auth-flow", "--repo", "alpha-repo"],
        )

        assert result.exit_code == 0
        assert "Change: add-auth-flow" in result.output
        assert "# Add Authentication Flow" in result.output

    def it_prints_text_error_for_unknown_change(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(
            cli, ["--format", "text", "openspec", "show", "nonexistent-change"]
        )

        assert result.exit_code != 0
        assert "Error: change 'nonexistent-change' not found" in result.output

    def it_prints_text_error_for_ambiguous_change(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(
            cli, ["--format", "text", "openspec", "show", "add-auth-flow"]
        )

        assert result.exit_code != 0
        assert "is ambiguous across repos" in result.output


class DescribeOpenspecSpecsFormat:
    def it_lists_specs_as_text_when_format_text_is_specified(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(
            cli, ["--format", "text", "openspec", "specs", "list", "--repo", "alpha-repo"]
        )

        assert result.exit_code == 0
        assert "Name: auth-flow" in result.output
        assert "Repo: alpha-repo" in result.output

    def it_shows_spec_content_as_text_when_format_text_is_specified(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(
            cli,
            ["--format", "text", "openspec", "specs", "show", "auth-flow", "--repo", "alpha-repo"],
        )

        assert result.exit_code == 0
        assert "# auth-flow (alpha-repo)" in result.output
        assert "auth-flow Specification" in result.output

    def it_prints_text_error_for_unknown_spec(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(Path("/tmp/fake-kb")))
        monkeypatch.setenv("KB_OPENSPEC_ROOT", str(OPENSPEC_FIXTURES))

        result = CliRunner().invoke(
            cli,
            ["--format", "text", "openspec", "specs", "show", "nope", "--repo", "alpha-repo"],
        )

        assert result.exit_code != 0
        assert "Error: spec 'nope' not found in repo 'alpha-repo'" in result.output
