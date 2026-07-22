"""kb's click-based CLI surface: bare invocation, --help, and `people`.

CliRunner drives the click Group directly, so these tests exercise the actual
argument parsing/dispatch instead of just calling build_app() in isolation
(that seam is already covered by test_main.py). The bare-invocation TUI path
can't run a real Textual event loop under CliRunner, so it's verified by
monkeypatching build_app and asserting it was called + run(), not by letting
the dashboard actually start.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

from click.testing import CliRunner

from kb.__main__ import cli

VAULT = Path(__file__).resolve().parents[1] / "fixtures" / "vault"


class DescribeBareInvocation:
    def it_launches_the_tui_dashboard_when_no_subcommand_is_given(self, monkeypatch):
        fake_app = MagicMock()
        fake_build_app = MagicMock(return_value=fake_app)
        monkeypatch.setattr("kb.__main__.build_app", fake_build_app)

        result = CliRunner().invoke(cli, [])

        assert result.exit_code == 0
        fake_build_app.assert_called_once()
        fake_app.run.assert_called_once()

    def it_does_not_launch_the_tui_when_a_subcommand_is_given(self, monkeypatch):
        fake_build_app = MagicMock()
        monkeypatch.setattr("kb.__main__.build_app", fake_build_app)
        monkeypatch.setenv("KB_ROOT", str(VAULT))

        CliRunner().invoke(cli, ["people", "list"])

        fake_build_app.assert_not_called()


class DescribeHelp:
    def it_exits_zero_and_lists_the_people_group(self):
        result = CliRunner().invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "people" in result.output


class DescribePeopleList:
    def it_prints_a_json_array_of_every_fixture_person(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(VAULT))

        result = CliRunner().invoke(cli, ["people", "list"])

        assert result.exit_code == 0
        people = json.loads(result.output)
        assert isinstance(people, list)
        assert len(people) == 4
        assert {"name", "title", "team", "email"} <= people[0].keys()

    def it_respects_the_kb_root_env_var_override(self, monkeypatch, tmp_path):
        (tmp_path / "people").mkdir()
        (tmp_path / "journal").mkdir()
        monkeypatch.setenv("KB_ROOT", str(tmp_path))

        result = CliRunner().invoke(cli, ["people", "list"])

        assert result.exit_code == 0
        assert json.loads(result.output) == []


class DescribePeopleShow:
    def it_prints_the_matching_persons_record_as_json(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(VAULT))

        result = CliRunner().invoke(cli, ["people", "show", "Marcus Webb"])

        assert result.exit_code == 0
        person = json.loads(result.output)
        assert person["name"] == "Marcus Webb"
        assert person["title"] == "Staff Software Engineer"
        assert person["team"] == "Engineering"

    def it_resolves_by_alias_not_just_the_canonical_name(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(VAULT))

        result = CliRunner().invoke(cli, ["people", "show", "mwebb"])

        assert result.exit_code == 0
        assert json.loads(result.output)["name"] == "Marcus Webb"

    def it_exits_non_zero_with_an_error_indication_for_an_unknown_name(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(VAULT))

        result = CliRunner().invoke(cli, ["people", "show", "Nobody Real"])

        assert result.exit_code != 0
        assert "not found" in (result.output + str(result.exception))


class DescribeCliQueryAndContract:
    def it_runs_query_and_returns_envelope_json(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(VAULT))

        result = CliRunner().invoke(cli, ["query", "-t", "gRPC"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["contract_version"]
        assert len(data["data"]["hits"]) > 0

    def it_supports_limit_option(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(VAULT))

        result = CliRunner().invoke(cli, ["query", "-l", "1"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert len(data["data"]["hits"]) == 1

    def it_prints_contract_version(self):
        result = CliRunner().invoke(cli, ["contract", "version"])

        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def it_prints_contract_schema(self):
        result = CliRunner().invoke(cli, ["contract", "schema"])

        assert result.exit_code == 0
        schema = json.loads(result.output)
        assert "ContractResponse" in schema
        assert "Profile" in schema

    def it_rejects_empty_json_string(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(VAULT))

        result = CliRunner().invoke(cli, ["query", "--json", ""])

        assert result.exit_code != 0
        data = json.loads(result.output)
        assert data["ok"] is False
        assert "Invalid QueryRequest JSON" in data["error"]["message"]


class DescribeJournalAppend:
    def it_writes_a_bare_body_through_the_engine(self, monkeypatch, tmp_path):
        (tmp_path / "people").mkdir()
        (tmp_path / "journal").mkdir()
        monkeypatch.setenv("KB_ROOT", str(tmp_path))

        result = CliRunner().invoke(
            cli, ["journal", "append", "--date", "2026-07-15", "--content", "Some test content"]
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        journal_file = tmp_path / "journal" / "2026-07-15.md"
        assert journal_file.read_text(encoding="utf-8") == "# 2026-07-15\n\nSome test content\n"

    def it_writes_content_under_a_named_section(self, monkeypatch, tmp_path):
        (tmp_path / "people").mkdir()
        (tmp_path / "journal").mkdir()
        monkeypatch.setenv("KB_ROOT", str(tmp_path))

        result = CliRunner().invoke(
            cli,
            [
                "journal",
                "append",
                "--date",
                "2026-07-15",
                "--section",
                "Git Activity",
                "--content",
                "- commit 1",
            ],
        )

        assert result.exit_code == 0
        journal_file = tmp_path / "journal" / "2026-07-15.md"
        assert journal_file.read_text(encoding="utf-8") == (
            "# 2026-07-15\n\n## Git Activity\n- commit 1\n"
        )

    def it_appends_to_an_existing_section_rather_than_overwriting_it(self, monkeypatch, tmp_path):
        (tmp_path / "people").mkdir()
        (tmp_path / "journal").mkdir()
        journal_file = tmp_path / "journal" / "2026-07-15.md"
        journal_file.write_text("# 2026-07-15\n\n## Git Activity\n- commit 1\n", encoding="utf-8")
        monkeypatch.setenv("KB_ROOT", str(tmp_path))

        result = CliRunner().invoke(
            cli,
            [
                "journal",
                "append",
                "--date",
                "2026-07-15",
                "--section",
                "Git Activity",
                "--content",
                "- commit 2",
            ],
        )

        assert result.exit_code == 0
        assert journal_file.read_text(encoding="utf-8") == (
            "# 2026-07-15\n\n## Git Activity\n- commit 1\n\n- commit 2\n"
        )

    def it_defaults_the_date_to_today(self, monkeypatch, tmp_path):
        (tmp_path / "people").mkdir()
        (tmp_path / "journal").mkdir()
        monkeypatch.setenv("KB_ROOT", str(tmp_path))

        result = CliRunner().invoke(cli, ["journal", "append", "--content", "note to self"])

        assert result.exit_code == 0
        today = date.today().strftime("%Y-%m-%d")
        journal_file = tmp_path / "journal" / f"{today}.md"
        assert journal_file.is_file()

    def it_reads_content_from_stdin_when_content_is_a_dash(self, monkeypatch, tmp_path):
        (tmp_path / "people").mkdir()
        (tmp_path / "journal").mkdir()
        monkeypatch.setenv("KB_ROOT", str(tmp_path))

        result = CliRunner().invoke(
            cli,
            ["journal", "append", "--date", "2026-07-15", "--content", "-"],
            input="piped content\n",
        )

        assert result.exit_code == 0
        journal_file = tmp_path / "journal" / "2026-07-15.md"
        assert journal_file.read_text(encoding="utf-8") == "# 2026-07-15\n\npiped content\n"

    def it_exits_non_zero_and_prints_the_error_envelope_for_an_invalid_date(
        self, monkeypatch, tmp_path
    ):
        (tmp_path / "people").mkdir()
        (tmp_path / "journal").mkdir()
        monkeypatch.setenv("KB_ROOT", str(tmp_path))

        result = CliRunner().invoke(
            cli, ["journal", "append", "--date", "not-a-date", "--content", "stuff"]
        )

        assert result.exit_code != 0
        data = json.loads(result.output)
        assert data["ok"] is False
        assert data["error"]["code"] == "validation.invalid_date"
        assert not (tmp_path / "journal" / "not-a-date.md").is_file()
