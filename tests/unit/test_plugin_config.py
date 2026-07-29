"""Loading dashboard layout + enabled-plugins config from TOML.

Zero config is the safe default: core panes in today's arrangement, no plugins
enabled. A config file lets the user pick which discovered plugins to import and
how many panes/rows the dashboard screen should compose.
"""

from pathlib import Path

import pytest

from kb.plugin_config import (
    DEFAULT_LAYOUT_ROWS,
    DashboardConfig,
    InvalidConfigError,
    load_config,
)


class DescribeLoadConfig:
    def it_returns_safe_defaults_when_the_config_file_does_not_exist(self, tmp_path):
        config = load_config(tmp_path / "does-not-exist.toml")

        assert config.enabled_plugins == []
        assert config.layout_rows == DEFAULT_LAYOUT_ROWS
        assert config.trigger_command is None

    def it_parses_enabled_plugins_list(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("[plugins]\nenabled = ['calendar']\n")

        config = load_config(path)

        assert config.enabled_plugins == ["calendar"]

    def it_parses_trigger_command(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("[trigger]\ncommand = 'aoe run --text {text}'\n")

        config = load_config(path)

        assert config.trigger_command == "aoe run --text {text}"

    def it_parses_layout_rows_list(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            "[layout]\n"
            'rows = [["kb.action-items", "calendar.upcoming"], '
            '["kb.action-items", "calendar.reminders"]]\n'
        )

        config = load_config(path)

        assert config.layout_rows == [
            ["kb.action-items", "calendar.upcoming"],
            ["kb.action-items", "calendar.reminders"],
        ]

    def it_tolerates_one_section_missing_but_not_malformed(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("[plugins]\nenabled = ['calendar']\n")

        config = load_config(path)

        assert config.enabled_plugins == ["calendar"]
        assert config.layout_rows == DEFAULT_LAYOUT_ROWS

    def it_parses_a_complete_file(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            "[plugins]\n"
            "enabled = ['calendar', 'jira']\n"
            "[layout]\n"
            "rows = [['kb.action-items']]\n"
        )

        config = load_config(path)

        assert config == DashboardConfig(
            enabled_plugins=["calendar", "jira"],
            layout_rows=[["kb.action-items"]],
            trigger_command=None,
        )

    def it_raises_invalid_config_for_malformed_toml(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("[plugins\nmissing bracket\n")

        with pytest.raises(InvalidConfigError):
            load_config(path)

    def it_raises_invalid_config_when_enabled_plugins_is_not_a_list(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("[plugins]\nenabled = 'not-a-list'\n")

        with pytest.raises(InvalidConfigError):
            load_config(path)

    def it_raises_invalid_config_when_enabled_plugins_contains_non_strings(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("[plugins]\nenabled = [123]\n")

        with pytest.raises(InvalidConfigError):
            load_config(path)

    def it_raises_invalid_config_when_layout_rows_is_not_a_list(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("[layout]\nrows = 'not-a-list'\n")

        with pytest.raises(InvalidConfigError):
            load_config(path)

    def it_raises_invalid_config_when_trigger_command_is_not_a_string(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("[trigger]\ncommand = 123\n")

        with pytest.raises(InvalidConfigError):
            load_config(path)

    def it_raises_invalid_config_when_trigger_is_a_scalar_string(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text('trigger = "agent"\n')

        with pytest.raises(InvalidConfigError):
            load_config(path)


class DescribeDefaultConfigPath:
    def it_points_at_xdg_config_home_when_set(self, tmp_path, monkeypatch):
        from kb.plugin_config import default_config_path

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        assert default_config_path() == tmp_path / "kb" / "config.toml"

    def it_falls_back_to_dot_config_when_xdg_is_unset(self, monkeypatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

        from kb.plugin_config import default_config_path

        assert default_config_path() == Path("~/.config/kb/config.toml").expanduser()
