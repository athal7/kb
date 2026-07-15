"""KB_ROOT resolution and vault-shape validation.

Resolution order: explicit arg -> $KB_ROOT env -> default ~/.local/share/kb.
Pointing at a directory that isn't a vault should fail fast with a clear error, so
a mistyped path is caught immediately rather than producing a mysteriously empty index.
"""

import pytest

from kb.config import InvalidVaultError, resolve_kb_root


class DescribeResolveKbRoot:
    def it_prefers_the_explicit_argument(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(tmp_path / "env"))

        assert resolve_kb_root(str(tmp_path / "arg")) == tmp_path / "arg"

    def it_falls_back_to_the_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(tmp_path / "env"))

        assert resolve_kb_root(None) == tmp_path / "env"

    def it_falls_back_to_the_default_when_nothing_is_set(self, monkeypatch):
        monkeypatch.delenv("KB_ROOT", raising=False)

        assert resolve_kb_root(None) == (
            __import__("pathlib").Path("~/.local/share/kb").expanduser()
        )

    def it_expands_user_home(self, monkeypatch):
        monkeypatch.delenv("KB_ROOT", raising=False)

        assert resolve_kb_root("~/somewhere").is_absolute()


class DescribeValidateVaultShape:
    def it_accepts_a_directory_with_people_and_journal(self, tmp_path):
        (tmp_path / "people").mkdir()
        (tmp_path / "journal").mkdir()

        # Should not raise.
        resolve_kb_root(str(tmp_path), validate=True)

    def it_raises_when_expected_subdirs_are_missing(self, tmp_path):
        with pytest.raises(InvalidVaultError):
            resolve_kb_root(str(tmp_path), validate=True)
