"""Loading dashboard layout + enabled-plugins config from TOML.

Zero config is the safe default: core panes in today's arrangement, no plugins
enabled. A config file lets the user pick which discovered plugins to import and
lay out all panes — core and plugin alike — as an ordered list of rows, each row an
ordered list of pane ids. Read with stdlib tomllib (no new dependency; the project
already requires Python >=3.12).
"""

from __future__ import annotations

import pytest

from kb.plugin_config import (
    DEFAULT_LAYOUT_ROWS,
    DashboardConfig,
    InvalidConfigError,
    load_config,
)


class DescribeLoadConfigDefaults:
    def it_returns_the_default_layout_and_no_plugins_when_the_file_is_absent(self, tmp_path):
        config = load_config(tmp_path / "does-not-exist.toml")

        assert config.enabled_plugins == []
        assert config.layout_rows == DEFAULT_LAYOUT_ROWS

    def it_defaults_to_the_current_dashboard_arrangement(self):
        # Documents the built-in default: action items spans both rows in the
        # first column (by appearing in both rows), calendar/reminders stack in
        # the second — mirroring today's hardcoded 2x2 grid exactly.
        assert DEFAULT_LAYOUT_ROWS == [
            ["kb.action-items", "calendar.upcoming"],
            ["kb.action-items", "calendar.reminders"],
        ]


class DescribeLoadConfigFromFile:
    def it_reads_the_enabled_plugin_list(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text('[plugins]\nenabled = ["calendar"]\n')

        config = load_config(path)

        assert config.enabled_plugins == ["calendar"]

    def it_reads_the_layout_rows(self, tmp_path):
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

    def it_uses_defaults_for_sections_the_file_omits(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text('[plugins]\nenabled = ["calendar"]\n')

        config = load_config(path)

        assert config.enabled_plugins == ["calendar"]
        assert config.layout_rows == DEFAULT_LAYOUT_ROWS

    def it_treats_an_empty_file_as_all_defaults(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("")

        config = load_config(path)

        assert config == DashboardConfig(
            enabled_plugins=[], layout_rows=DEFAULT_LAYOUT_ROWS
        )


class DescribeLoadConfigErrors:
    def it_raises_a_clear_error_on_malformed_toml(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("this is = = not toml")

        with pytest.raises(InvalidConfigError):
            load_config(path)

    def it_rejects_a_non_list_layout_rows(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text('[layout]\nrows = "nope"\n')

        with pytest.raises(InvalidConfigError):
            load_config(path)

    def it_rejects_a_row_that_is_not_a_list_of_strings(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("[layout]\nrows = [[1, 2]]\n")

        with pytest.raises(InvalidConfigError):
            load_config(path)

    def it_rejects_a_non_list_enabled(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text('[plugins]\nenabled = "calendar"\n')

        with pytest.raises(InvalidConfigError):
            load_config(path)


class DescribeDefaultConfigPath:
    def it_points_at_xdg_config_home_when_set(self, tmp_path, monkeypatch):
        from kb.plugin_config import default_config_path

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        assert default_config_path() == tmp_path / "kb" / "config.toml"

    def it_falls_back_to_dot_config_when_xdg_is_unset(self, monkeypatch):
        from pathlib import Path

        from kb.plugin_config import default_config_path

        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

        assert default_config_path() == Path("~/.config/kb/config.toml").expanduser()
