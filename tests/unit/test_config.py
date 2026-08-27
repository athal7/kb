"""KB_ROOT resolution, config-file get/set, and vault-shape validation.

Resolution order: explicit arg -> $KB_ROOT env -> config-file `path` -> default
~/.local/share/kb. Pointing at a directory that isn't a vault should fail fast with
a clear error, so a mistyped path is caught immediately rather than producing a
mysteriously empty index.

The config get/set surface is validated against a fixed key registry, so a typo is
rejected instead of silently writing a key nothing ever reads.
"""

import pytest

from kb.config import (
    InvalidConfigError,
    InvalidVaultError,
    UnknownConfigKeyError,
    get_config_value,
    resolve_kb_root,
    set_config_value,
)


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    """Point the config file at an empty tmp dir so tests never read the real one."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


class DescribeResolveKbRoot:
    def it_prefers_the_explicit_argument(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(tmp_path / "env"))

        assert resolve_kb_root(str(tmp_path / "arg")) == tmp_path / "arg"

    def it_falls_back_to_the_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(tmp_path / "env"))

        assert resolve_kb_root(None) == tmp_path / "env"

    def it_uses_the_config_file_path_when_env_is_unset(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KB_ROOT", raising=False)
        set_config_value("path", str(tmp_path / "vault"))

        assert resolve_kb_root(None) == tmp_path / "vault"

    def it_prefers_env_over_the_config_file_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(tmp_path / "env"))
        set_config_value("path", str(tmp_path / "vault"))

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


class DescribeGetConfigValue:
    def it_returns_the_default_when_unset(self):
        assert get_config_value("path") == "~/.local/share/kb"

    def it_returns_the_stored_value_after_set(self):
        set_config_value("path", "~/.kb")

        assert get_config_value("path") == "~/.kb"

    def it_raises_for_an_unknown_key(self):
        with pytest.raises(UnknownConfigKeyError):
            get_config_value("nope")

    def it_raises_invalid_config_for_malformed_toml(self, tmp_path):
        cfg = tmp_path / "xdg" / "kb" / "config.toml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("this is = not = valid toml")

        with pytest.raises(InvalidConfigError):
            get_config_value("path")


class DescribeSetConfigValue:
    def it_creates_the_config_file_if_missing(self, tmp_path):
        set_config_value("path", "~/.kb")

        cfg = tmp_path / "xdg" / "kb" / "config.toml"
        assert cfg.exists()
        assert "~/.kb" in cfg.read_text()

    def it_overwrites_a_previous_value(self):
        set_config_value("path", "~/.kb")
        set_config_value("path", "~/.other")

        assert get_config_value("path") == "~/.other"

    def it_preserves_other_config_sections(self, tmp_path):
        cfg = tmp_path / "xdg" / "kb" / "config.toml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text('[plugins]\nenabled = ["calendar"]\n')

        set_config_value("path", "~/.kb")

        import tomllib

        data = tomllib.loads(cfg.read_text())
        assert data["plugins"]["enabled"] == ["calendar"]
        assert data["core"]["path"] == "~/.kb"

    def it_raises_for_an_unknown_key(self):
        with pytest.raises(UnknownConfigKeyError):
            set_config_value("nope", "value")
