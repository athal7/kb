"""Configuration: KB_ROOT resolution and vault-shape validation.

Resolution precedence: explicit argument > $KB_ROOT env var > default. Optional
validation fails fast if the resolved path lacks the expected vault shape, turning a
mistyped path into a clear error instead of a silently empty index.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_KB_ROOT = "~/.local/share/kb"
_REQUIRED_SUBDIRS = ("people", "journal")


class InvalidVaultError(Exception):
    """Raised when a resolved KB root does not look like a knowledge-base vault."""


def resolve_kb_root(arg: str | None, *, validate: bool = False) -> Path:
    """Resolve the KB root path, optionally validating its shape.

    Precedence: `arg` > `$KB_ROOT` > DEFAULT_KB_ROOT. `~` is expanded.
    """
    raw = arg or os.environ.get("KB_ROOT") or DEFAULT_KB_ROOT
    path = Path(raw).expanduser()

    if validate:
        missing = [d for d in _REQUIRED_SUBDIRS if not (path / d).is_dir()]
        if missing:
            raise InvalidVaultError(
                f"{path} does not look like a KB vault (missing: {', '.join(missing)})"
            )

    return path
