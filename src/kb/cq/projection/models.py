"""Durable typed state for isolated local CQ projection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class ProjectionScope(StrEnum):
    PEOPLE = "people"
    PROJECTS = "projects"
    PRODUCTS = "products"
    DECISIONS = "decisions"
    STANDING = "standing"


class ProjectionAction(StrEnum):
    CREATE = "create"
    REPLACE = "replace"
    UNCHANGED = "unchanged"
    STALE = "stale"


class AccessClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CLASSIFIED = "classified"


ALL_LOCAL_AGENTS_POLICY = "all-local-agents"
MANIFEST_VERSION = 2
LEDGER_VERSION = 2


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ProjectionSource:
    """One focused, independently retrievable fact unit from a KB record."""

    scope: ProjectionScope
    source_path: str
    fragment: str
    fingerprint: str
    classification: AccessClassification
    entity_name: str
    aliases: list[str]
    summary: str
    detail: str
    action: str
    domains: list[str]
    identity_domain: str
    marker: str

    @property
    def key(self) -> str:
        return f"{self.scope.value}:{self.source_path}#{self.fragment}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["scope"] = self.scope.value
        data["classification"] = self.classification.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectionSource:
        return cls(
            scope=ProjectionScope(data["scope"]),
            source_path=data["source_path"],
            fragment=data["fragment"],
            fingerprint=data["fingerprint"],
            classification=AccessClassification(data["classification"]),
            entity_name=data["entity_name"],
            aliases=list(data["aliases"]),
            summary=data["summary"],
            detail=data["detail"],
            action=data["action"],
            domains=list(data["domains"]),
            identity_domain=data["identity_domain"],
            marker=data["marker"],
        )


@dataclass(frozen=True)
class ProjectionOperation:
    action: ProjectionAction
    source: ProjectionSource
    previous_ku_ids: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "source": self.source.to_dict(),
            "previous_ku_ids": self.previous_ku_ids,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectionOperation:
        return cls(
            action=ProjectionAction(data["action"]),
            source=ProjectionSource.from_dict(data["source"]),
            previous_ku_ids=list(data.get("previous_ku_ids", [])),
            reason=data.get("reason", ""),
        )


@dataclass(frozen=True)
class ProjectionManifest:
    target_db: str
    authorization_policy: str | None
    scope_expectations: dict[str, list[str]]
    operations: list[ProjectionOperation]
    approved_digest: str | None = None
    created_at: str = field(default_factory=utc_now)
    version: int = MANIFEST_VERSION

    @property
    def approved(self) -> bool:
        return self.approved_digest == self.content_digest()

    def content_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "target_db": self.target_db,
            "authorization_policy": self.authorization_policy,
            "scope_expectations": self.scope_expectations,
            "operations": [operation.to_dict() for operation in self.operations],
        }

    def content_digest(self) -> str:
        return digest(self.content_dict())

    def approve(self) -> ProjectionManifest:
        return ProjectionManifest(
            target_db=self.target_db,
            authorization_policy=self.authorization_policy,
            scope_expectations=self.scope_expectations,
            operations=self.operations,
            approved_digest=self.content_digest(),
            created_at=self.created_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.content_dict(),
            "approved_digest": self.approved_digest,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectionManifest:
        if data.get("version") != MANIFEST_VERSION:
            raise ValueError("unsupported projection manifest version")
        return cls(
            target_db=data["target_db"],
            authorization_policy=data.get("authorization_policy"),
            scope_expectations={
                str(scope): list(keys) for scope, keys in data.get("scope_expectations", {}).items()
            },
            operations=[ProjectionOperation.from_dict(item) for item in data["operations"]],
            approved_digest=data.get("approved_digest"),
            created_at=data["created_at"],
            version=data["version"],
        )


@dataclass
class LedgerRecord:
    scope: ProjectionScope
    source_path: str
    fragment: str
    source_fingerprint: str
    classification: AccessClassification
    identity_domain: str
    marker: str
    active_ku_ids: list[str] = field(default_factory=list)
    replaced_ku_ids: list[str] = field(default_factory=list)
    stale: bool = False
    updated_at: str = field(default_factory=utc_now)

    @property
    def key(self) -> str:
        return f"{self.scope.value}:{self.source_path}#{self.fragment}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["scope"] = self.scope.value
        data["classification"] = self.classification.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LedgerRecord:
        return cls(
            scope=ProjectionScope(data["scope"]),
            source_path=data["source_path"],
            fragment=data["fragment"],
            source_fingerprint=data["source_fingerprint"],
            classification=AccessClassification(data["classification"]),
            identity_domain=data["identity_domain"],
            marker=data["marker"],
            active_ku_ids=list(data.get("active_ku_ids", [])),
            replaced_ku_ids=list(data.get("replaced_ku_ids", [])),
            stale=bool(data.get("stale", False)),
            updated_at=data["updated_at"],
        )


@dataclass
class PendingOperation:
    operation: ProjectionOperation
    created_ku_ids: list[str] = field(default_factory=list)
    staled_ku_ids: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return self.operation.source.key

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation.to_dict(),
            "created_ku_ids": self.created_ku_ids,
            "staled_ku_ids": self.staled_ku_ids,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PendingOperation:
        return cls(
            operation=ProjectionOperation.from_dict(data["operation"]),
            created_ku_ids=list(data.get("created_ku_ids", [])),
            staled_ku_ids=list(data.get("staled_ku_ids", [])),
        )


@dataclass(frozen=True)
class ScopeCompletion:
    scope: ProjectionScope
    expected: int
    active: int
    stale: int
    backfill_complete_at: str | None
    complete: bool

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["scope"] = self.scope.value
        return data
