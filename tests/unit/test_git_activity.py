"""Tests for git-commit-activity journal collector."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from collectors.git_activity import get_current_git_user, get_git_stats


def test_get_current_git_user():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="Jane Doe\n", returncode=0)
        assert get_current_git_user(Path(".")) == "Jane Doe"

        mock_run.side_effect = Exception("error")
        assert get_current_git_user(Path(".")) is None


def test_get_git_stats_non_existent():
    assert get_git_stats(Path("/non/existent/path"), "2026-07-15") is None


def test_get_git_stats_not_in_work_tree():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="false\n", returncode=0)
        assert get_git_stats(Path("."), "2026-07-15") is None


def test_get_git_stats_success():
    mock_output = (
        "abc1234 Commit message 1\n"
        " 3 files changed, 45 insertions(+), 12 deletions(-)\n"
        "def5678 Commit message 2\n"
        " 1 file changed, 2 insertions(+)\n"
    )
    with patch("subprocess.run") as mock_run:
        # First call is is-inside-work-tree, second call is git log
        mock_run.side_effect = [
            MagicMock(stdout="true\n", returncode=0),
            MagicMock(stdout=mock_output, returncode=0),
        ]

        stats = get_git_stats(Path("."), "2026-07-15")
        assert stats is not None
        assert stats["commits"] == 2
        assert stats["files_changed"] == 4
        assert stats["insertions"] == 47
        assert stats["deletions"] == 12


def test_get_git_stats_no_activity():
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout="true\n", returncode=0),
            MagicMock(stdout="", returncode=0),
        ]

        stats = get_git_stats(Path("."), "2026-07-15")
        assert stats is None


class DescribeCollectorMain:
    @patch("sys.exit")
    @patch("subprocess.run")
    def test_dry_run(self, mock_run, mock_exit, capsys):
        from collectors.git_activity import main

        # Make sys.exit raise SystemExit to prevent execution of the non-dry-run path
        mock_exit.side_effect = SystemExit(0)

        # Mock the git worktree check to return True and config user.name to Jane Doe
        # And git log to return some dummy output
        mock_run.side_effect = [
            MagicMock(stdout="Jane Doe\n", returncode=0),  # get_current_git_user
            MagicMock(stdout="true\n", returncode=0),      # is-inside-work-tree
            MagicMock(
                stdout="abc1234 msg\n 1 file changed, 5 insertions(+)\n", returncode=0
            ),  # git log
        ]

        # Call main with mock arguments
        with patch(
            "sys.argv",
            [
                "collectors/git_activity.py",
                "--date",
                "2026-07-15",
                "--dry-run",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        mock_exit.assert_called_once_with(0)
        captured = capsys.readouterr()
        assert "--- DRY RUN ---" in captured.out
        assert "Date: 2026-07-15" in captured.out
        assert "Section: Git Activity" in captured.out
        repo_name = Path(".").resolve().name
        assert f"- **{repo_name}**: 1 commit, 1 file changed (+5/-0 lines)" in captured.out

    @patch("sys.exit")
    @patch("subprocess.run")
    def test_successful_append(self, mock_run, mock_exit, capsys):
        from collectors.git_activity import main

        mock_run.side_effect = [
            MagicMock(stdout="Jane Doe\n", returncode=0),  # get_current_git_user
            MagicMock(stdout="true\n", returncode=0),      # is-inside-work-tree
            MagicMock(
                stdout="abc1234 msg\n 1 file changed, 5 insertions(+)\n", returncode=0
            ),  # git log
            MagicMock(stdout="{'ok': true}", returncode=0),  # kb append invocation
        ]

        with patch(
            "sys.argv",
            ["collectors/git_activity.py", "--date", "2026-07-15"],
        ):
            main()

        mock_exit.assert_not_called()
        captured = capsys.readouterr()
        assert "Successfully logged git activity stats" in captured.out

    @patch("sys.exit")
    @patch("subprocess.run")
    def test_repo_directory_scanning(self, mock_run, mock_exit, tmp_path):
        from collectors.git_activity import main

        # Create some fake repo dirs
        repo1 = tmp_path / "repo1"
        repo1.mkdir()
        (repo1 / ".git").mkdir()

        repo2 = tmp_path / "repo2"
        repo2.mkdir()
        (repo2 / ".git").mkdir()

        # Non-repo dir
        (tmp_path / "other").mkdir()

        # Mock runs:
        # For repo1: user name config, is-inside check, git log
        # For repo2: user name config, is-inside check, git log
        # For final append call
        mock_run.side_effect = [
            MagicMock(stdout="Jane Doe\n", returncode=0),  # repo1 user.name
            MagicMock(stdout="true\n", returncode=0),      # repo1 worktree
            MagicMock(
                stdout="abc1234 msg\n 1 file changed, 5 insertions(+)\n", returncode=0
            ),  # repo1 log
            MagicMock(stdout="Jane Doe\n", returncode=0),  # repo2 user.name
            MagicMock(stdout="true\n", returncode=0),      # repo2 worktree
            MagicMock(
                stdout="def5678 msg2\n 2 files changed, 2 deletions(-)\n", returncode=0
            ),  # repo2 log
            MagicMock(stdout="{'ok': true}", returncode=0),  # final kb append call
        ]

        with patch(
            "sys.argv",
            [
                "collectors/git_activity.py",
                "--dir",
                str(tmp_path),
                "--date",
                "2026-07-15",
            ],
        ):
            main()

        # Verify kb command was called with content containing both repos
        called_cmd = mock_run.call_args_list[-1][0][0]
        assert "append" in called_cmd
        # Look for the --content index
        content_idx = called_cmd.index("--content") + 1
        content_val = called_cmd[content_idx]
        assert "- **repo1**: 1 commit, 1 file changed (+5/-0 lines)" in content_val
        assert "- **repo2**: 1 commit, 2 files changed (+0/-2 lines)" in content_val
