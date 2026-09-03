"""Fail-closed safety gates for the isolated local CQ projection path."""

from __future__ import annotations

import re
from typing import Any

from kb.cq.projection.models import ALL_LOCAL_AGENTS_POLICY, AccessClassification


class ProjectionSafetyError(RuntimeError):
    pass


_SECRET_VALUE = re.compile(
    r"(?:api[_-]?key|secret|token|password|private[_-]?key)\s*[:=]\s*\S+",
    re.IGNORECASE,
)
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")


def require_no_source_secrets(text: str) -> None:
    if _PRIVATE_KEY.search(text) or _SECRET_VALUE.search(text):
        raise ProjectionSafetyError("source record contains a credential or secret")


def access_classification(metadata: dict, default: AccessClassification) -> AccessClassification:
    """Use only canonical access metadata, with a documented scope default."""
    value = metadata.get("access", metadata.get("classification", default.value))
    if not isinstance(value, str):
        raise ProjectionSafetyError("canonical access metadata must be a string")
    try:
        return AccessClassification(value.lower())
    except ValueError as exc:
        raise ProjectionSafetyError(f"unsupported canonical access class: {value}") from exc


def require_access_authorization(
    classification: AccessClassification, authorization_policy: str | None
) -> None:
    if classification is AccessClassification.PUBLIC:
        return
    if authorization_policy != ALL_LOCAL_AGENTS_POLICY:
        raise ProjectionSafetyError(
            "internal or classified content requires --authorization-policy all-local-agents"
        )


def require_clean_cq_status(status: Any) -> None:
    def values(node: Any) -> list[tuple[str, Any]]:
        if isinstance(node, dict):
            return [
                item
                for key, value in node.items()
                for item in [(str(key).lower(), value), *values(value)]
            ]
        if isinstance(node, list):
            return [item for value in node for item in values(value)]
        return []

    for key, value in values(status):
        if "drain" in key and value:
            raise ProjectionSafetyError("CQ status reports drain mode")
        if "remote" in key and "auth" in key and value:
            raise ProjectionSafetyError("CQ status reports remote authentication")
