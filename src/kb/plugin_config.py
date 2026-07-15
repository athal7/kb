"""Dashboard layout + enabled-plugins configuration.

Read from ``~/.config/kb/config.toml`` (honoring ``$XDG_CONFIG_HOME``) with stdlib
``tomllib`` — no new dependency, since the project already requires Python >=3.12.

The config unifies core and plugin panes under one layout model: ``[layout].rows``
is an ordered list of rows, each an ordered list of pane ids, and core pane ids
(``kb.action-items``) sit alongside plugin pane ids (``calendar.upcoming``) with no
distinction. ``[plugins].enabled`` lists the entry-point names to actually import —
a plugin is discovered cheaply from metadata but only loaded (and its heavy deps
imported) when named here, so the safe zero-config default is core panes only.

This module is pure Python and stays free of Textual — it only parses config into a
`DashboardConfig`; the loader (plugin_loader.py) turns that into a live pane
registry.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

# Reproduces today's hardcoded 2x2 grid using only core pane ids, with no
# plugins enabled. Action items appears in both rows, which is how the layout
# expresses "spans both rows" (see DashboardScreen.compose); calendar and
# reminders stack in the other column, one per row. A user who installs the
# app but writes no config sees exactly what they saw before the plugin
# system existed.
DEFAULT_LAYOUT_ROWS: list[list[str]] = [
    ["kb.action-items", "calendar.upcoming"],
    ["kb.action-items", "calendar.reminders"],
]


class InvalidConfigError(Exception):
    """Raised when the config file is malformed or has the wrong shape."""


@dataclass(frozen=True)
class DashboardConfig:
    enabled_plugins: list[str]
    layout_rows: list[list[str]]


def default_config_path() -> Path:
    """Resolve the config path: ``$XDG_CONFIG_HOME/kb/config.toml`` or ``~/.config``."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path("~/.config").expanduser()
    return base / "kb" / "config.toml"


def load_config(path: Path) -> DashboardConfig:
    """Load config from ``path``, falling back to safe defaults for anything absent.

    A missing file yields the default (core panes, no plugins). A present but
    malformed or wrongly-shaped file raises `InvalidConfigError` rather than
    silently degrading, so a typo is caught immediately instead of quietly
    dropping panes.
    """
    if not path.exists():
        return DashboardConfig(
            enabled_plugins=[], layout_rows=list(DEFAULT_LAYOUT_ROWS)
        )

    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise InvalidConfigError(f"{path} is not valid TOML: {exc}") from exc

    return DashboardConfig(
        enabled_plugins=_parse_enabled(data, path),
        layout_rows=_parse_layout_rows(data, path),
    )


def _parse_enabled(data: dict, path: Path) -> list[str]:
    plugins = data.get("plugins", {})
    enabled = plugins.get("enabled")
    if enabled is None:
        return []
    if not isinstance(enabled, list) or not all(isinstance(x, str) for x in enabled):
        raise InvalidConfigError(
            f"{path}: [plugins].enabled must be a list of strings"
        )
    return enabled


def _parse_layout_rows(data: dict, path: Path) -> list[list[str]]:
    layout = data.get("layout", {})
    rows = layout.get("rows")
    if rows is None:
        return list(DEFAULT_LAYOUT_ROWS)
    if not isinstance(rows, list):
        raise InvalidConfigError(f"{path}: [layout].rows must be a list of rows")
    for row in rows:
        if not isinstance(row, list) or not all(isinstance(x, str) for x in row):
            raise InvalidConfigError(
                f"{path}: each [layout].rows entry must be a list of pane-id strings"
            )
    return rows
