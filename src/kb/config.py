"""Configuration: KB_ROOT resolution, config-file get/set, and vault-shape validation.

Resolution precedence for the KB root: explicit argument > ``$KB_ROOT`` env var >
config-file ``path`` value > default. Optional validation fails fast if the
resolved path lacks the expected vault shape, turning a mistyped path into a
clear error instead of a silently empty index.

The config file (``~/.config/kb/config.toml``, see
:func:`kb.plugin_config.default_config_path`) also holds the user-settable flags
managed by ``kb config get/set``. Only keys declared in :data:`SETTABLE_KEYS` are
readable/writable, so a typo is rejected instead of silently writing an ignored
key. ``kb config set`` preserves any other content already in the file (for
example the ``[layout]``/``[plugins]`` dashboard tables).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

import tomli_w

from kb.plugin_config import default_config_path

DEFAULT_KB_ROOT = "~/.local/share/kb"
_REQUIRED_SUBDIRS = ("people", "journal")


class InvalidVaultError(Exception):
    """Raised when a resolved KB root does not look like a knowledge-base vault."""


class UnknownConfigKeyError(Exception):
    """Raised when a config key is not a recognized, settable flag."""


class InvalidConfigError(Exception):
    """Raised when the config file is present but not valid TOML or wrongly shaped."""


@dataclass(frozen=True)
class ConfigKey:
    """A user-settable config flag: where it lives in the TOML file and its default."""

    name: str
    section: str
    default: str | None = None


# The set of flags ``kb config get/set`` understands. Extend this to expose more
# config-file parameters; get/set validate against it so unknown keys are rejected.
SETTABLE_KEYS: dict[str, ConfigKey] = {
    "path": ConfigKey(name="path", section="core", default=DEFAULT_KB_ROOT),
}


def _resolve_key(key: str) -> ConfigKey:
    try:
        return SETTABLE_KEYS[key]
    except KeyError:
        known = ", ".join(sorted(SETTABLE_KEYS))
        raise UnknownConfigKeyError(
            f"unknown config key '{key}' (known keys: {known})"
        ) from None


def _read_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise InvalidConfigError(f"{path} is not valid TOML: {exc}") from exc


def _stored_value(spec: ConfigKey, path: Path) -> str | None:
    """The raw string stored for ``spec`` in the config file, or ``None`` if unset."""
    section = _read_config(path).get(spec.section, {})
    if not isinstance(section, dict):
        raise InvalidConfigError(f"{path}: [{spec.section}] must be a table")
    value = section.get(spec.name)
    if value is not None and not isinstance(value, str):
        raise InvalidConfigError(f"{path}: [{spec.section}].{spec.name} must be a string")
    return value


def get_config_value(key: str, *, config_path: Path | None = None) -> str | None:
    """Return the configured value for ``key``, or its default if unset.

    Reads only the config file; runtime overrides such as ``$KB_ROOT`` are not
    consulted here. Raises :class:`UnknownConfigKeyError` for unrecognized keys.
    """
    spec = _resolve_key(key)
    stored = _stored_value(spec, config_path or default_config_path())
    return stored if stored is not None else spec.default


def set_config_value(key: str, value: str, *, config_path: Path | None = None) -> None:
    """Persist ``value`` for ``key`` in the config file, creating it if needed.

    Preserves any other content already in the file. Raises
    :class:`UnknownConfigKeyError` for unrecognized keys.
    """
    spec = _resolve_key(key)
    path = config_path or default_config_path()
    data = _read_config(path)
    section = data.setdefault(spec.section, {})
    if not isinstance(section, dict):
        raise InvalidConfigError(f"{path}: [{spec.section}] must be a table")
    section[spec.name] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(data))


def resolve_kb_root(arg: str | None, *, validate: bool = False) -> Path:
    """Resolve the KB root path, optionally validating its shape.

    Precedence: `arg` > `$KB_ROOT` > config-file `path` > DEFAULT_KB_ROOT. `~` is
    expanded.
    """
    raw = (
        arg
        or os.environ.get("KB_ROOT")
        or _stored_value(SETTABLE_KEYS["path"], default_config_path())
        or DEFAULT_KB_ROOT
    )
    path = Path(raw).expanduser()

    if validate:
        missing = [d for d in _REQUIRED_SUBDIRS if not (path / d).is_dir()]
        if missing:
            raise InvalidVaultError(
                f"{path} does not look like a KB vault (missing: {', '.join(missing)})"
            )

    return path
