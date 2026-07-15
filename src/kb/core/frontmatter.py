"""Tolerant YAML frontmatter splitting.

Vault files come in two shapes: with a leading `---` YAML block (people, projects,
products) and with none at all (journal, decisions). Human-written frontmatter drifts
and occasionally breaks. Parsing never raises; malformed or non-mapping frontmatter is
reported as a warning and treated as absent, so a single bad file can't take down a scan.
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

_DELIM = "---"


@dataclass(frozen=True)
class SplitResult:
    frontmatter: dict | None
    body: str
    warning: str | None = None


def split(text: str) -> SplitResult:
    """Split `text` into (frontmatter mapping, body).

    Returns frontmatter=None when there is no block or when the block is malformed
    or not a mapping; in the malformed/non-mapping cases `warning` describes why.
    """
    if not text.startswith(_DELIM + "\n") and text != _DELIM:
        return SplitResult(frontmatter=None, body=text)

    # Find the closing delimiter line after the opening one.
    lines = text.split("\n")
    close_idx = None
    for i in range(1, len(lines)):
        if lines[i] == _DELIM:
            close_idx = i
            break

    if close_idx is None:
        # An opening delimiter with no close is not a frontmatter block; treat as body.
        return SplitResult(frontmatter=None, body=text)

    raw_fm = "\n".join(lines[1:close_idx])
    body = "\n".join(lines[close_idx + 1 :])

    try:
        parsed = yaml.safe_load(raw_fm)
    except yaml.YAMLError as exc:
        return SplitResult(frontmatter=None, body=body, warning=f"malformed frontmatter: {exc}")

    if parsed is None:
        return SplitResult(frontmatter={}, body=body)

    if not isinstance(parsed, dict):
        return SplitResult(
            frontmatter=None,
            body=body,
            warning=f"frontmatter is not a mapping (got {type(parsed).__name__})",
        )

    return SplitResult(frontmatter=parsed, body=body)
