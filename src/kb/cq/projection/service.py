"""Crash-recoverable apply and exact identity verification."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from kb.cq.projection.cq_cli import CQCli
from kb.cq.projection.ledger import ProjectionLedger
from kb.cq.projection.lock import ProjectionLock
from kb.cq.projection.models import (
    LedgerRecord,
    PendingOperation,
    ProjectionAction,
    ProjectionManifest,
    ProjectionOperation,
    ProjectionScope,
    ProjectionSource,
    utc_now,
)
from kb.cq.projection.planner import build_plan
from kb.cq.projection.safety import (
    ProjectionSafetyError,
    require_access_authorization,
)


class ProjectionCQClient(Protocol):
    def status(self) -> dict: ...

    def propose(self, source: ProjectionSource) -> str: ...

    def stale(self, ku_id: str) -> None: ...

    def find_identity(self, identity_domain: str) -> dict[str, dict]: ...


@dataclass(frozen=True)
class ApplyResult:
    source_path: str
    fragment: str
    scope: ProjectionScope
    action: ProjectionAction
    created_ku_ids: list[str]
    staled_ku_ids: list[str]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["scope"] = self.scope.value
        data["action"] = self.action.value
        return data


@dataclass(frozen=True)
class VerificationResult:
    source_path: str
    fragment: str
    scope: ProjectionScope
    expected_ku_ids: list[str]
    active_ku_ids: list[str]
    valid: bool
    reason: str

    @property
    def key(self) -> str:
        return f"{self.scope.value}:{self.source_path}#{self.fragment}"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["scope"] = self.scope.value
        return data


def apply_manifest(
    *,
    manifest: ProjectionManifest,
    ledger: ProjectionLedger,
    kb_root: Path,
    target_db: Path,
    cq: ProjectionCQClient | None = None,
) -> list[ApplyResult]:
    """Recover prior work, then revalidate the complete source plan under lock."""
    if not manifest.approved:
        raise ProjectionSafetyError("manifest approval digest is missing or invalid")
    if target_db.expanduser().resolve() != Path(manifest.target_db).expanduser().resolve():
        raise ProjectionSafetyError("manifest target does not match configured CQ target")
    client = cq or CQCli()
    client.status()
    with ProjectionLock(ledger.path):
        _recover_pending(ledger, client)
        _validate_manifest_sources(manifest, ledger, kb_root)
        results = [_apply_operation(ledger, client, operation) for operation in manifest.operations]
        ledger.set_scope_expectations(manifest.scope_expectations)
        scopes = tuple(ProjectionScope(scope) for scope in manifest.scope_expectations)
        _verify_scopes(ledger=ledger, cq=client, scopes=scopes)
    return [result for result in results if result is not None]


def _apply_operation(
    ledger: ProjectionLedger, client: ProjectionCQClient, operation: ProjectionOperation
) -> ApplyResult | None:
    if operation.action is ProjectionAction.UNCHANGED:
        return None
    existing = ledger.get(
        operation.source.scope, operation.source.source_path, operation.source.fragment
    )
    if (
        operation.action is not ProjectionAction.STALE
        and existing is not None
        and existing.source_fingerprint == operation.source.fingerprint
        and existing.active_ku_ids
        and not existing.stale
    ):
        return None
    pending = PendingOperation(operation)
    ledger.put_pending(pending)
    return _continue_pending(ledger, client, pending)


def _recover_pending(ledger: ProjectionLedger, client: ProjectionCQClient) -> None:
    for pending in ledger.pending():
        _continue_pending(ledger, client, pending)


def _continue_pending(
    ledger: ProjectionLedger, client: ProjectionCQClient, pending: PendingOperation
) -> ApplyResult:
    operation = pending.operation
    if operation.action is not ProjectionAction.STALE and not pending.created_ku_ids:
        existing = client.find_identity(operation.source.identity_domain)
        if len(existing) > 1:
            raise ProjectionSafetyError("projection identity maps to multiple CQ KUs")
        pending.created_ku_ids = list(existing) or [client.propose(operation.source)]
        ledger.put_pending(pending)
    for ku_id in operation.previous_ku_ids:
        if ku_id not in pending.staled_ku_ids:
            client.stale(ku_id)
            pending.staled_ku_ids.append(ku_id)
            ledger.put_pending(pending)
    if operation.action is ProjectionAction.STALE:
        record = ledger.get(
            operation.source.scope, operation.source.source_path, operation.source.fragment
        )
        if record is not None:
            record.active_ku_ids = []
            record.replaced_ku_ids = sorted(set(record.replaced_ku_ids + pending.staled_ku_ids))
            record.stale = True
            record.updated_at = utc_now()
            ledger.put(record)
    else:
        ledger.put(
            LedgerRecord(
                scope=operation.source.scope,
                source_path=operation.source.source_path,
                fragment=operation.source.fragment,
                source_fingerprint=operation.source.fingerprint,
                classification=operation.source.classification,
                identity_domain=operation.source.identity_domain,
                marker=operation.source.marker,
                active_ku_ids=pending.created_ku_ids,
                replaced_ku_ids=pending.staled_ku_ids,
                stale=False,
            )
        )
    ledger.remove_pending(pending)
    return ApplyResult(
        operation.source.source_path,
        operation.source.fragment,
        operation.source.scope,
        operation.action,
        pending.created_ku_ids,
        pending.staled_ku_ids,
    )


def _validate_manifest_sources(
    manifest: ProjectionManifest, ledger: ProjectionLedger, kb_root: Path
) -> None:
    try:
        scopes = tuple(ProjectionScope(scope) for scope in manifest.scope_expectations)
    except ValueError as exc:
        raise ProjectionSafetyError("manifest has unsupported scope expectation") from exc
    fresh = build_plan(
        kb_root=kb_root,
        ledger=ledger,
        target_db=Path(manifest.target_db),
        authorization_policy=manifest.authorization_policy,
        scopes=scopes,
    )
    if fresh.scope_expectations != manifest.scope_expectations:
        raise ProjectionSafetyError("canonical source set changed after approval")
    fresh_sources = {
        operation.source.key: operation.source
        for operation in fresh.operations
        if operation.action is not ProjectionAction.STALE
    }
    for operation in manifest.operations:
        require_access_authorization(operation.source.classification, manifest.authorization_policy)
        current = ledger.get(
            operation.source.scope, operation.source.source_path, operation.source.fragment
        )
        if operation.action is ProjectionAction.STALE:
            if current is None or current.active_ku_ids != operation.previous_ku_ids:
                raise ProjectionSafetyError("stale operation no longer matches ledger")
            continue
        current_source = fresh_sources.get(operation.source.key)
        if current_source is None or current_source.to_dict() != operation.source.to_dict():
            raise ProjectionSafetyError("canonical projection source changed after approval")
        if operation.action is ProjectionAction.CREATE and current is not None:
            if current.source_fingerprint != operation.source.fingerprint or current.stale:
                raise ProjectionSafetyError("create operation conflicts with ledger mapping")
        elif operation.action is ProjectionAction.REPLACE:
            if current is None:
                raise ProjectionSafetyError("replacement operation has no ledger mapping")
            if current.active_ku_ids != operation.previous_ku_ids and (
                current.source_fingerprint != operation.source.fingerprint or current.stale
            ):
                raise ProjectionSafetyError("replacement operation conflicts with ledger mapping")


def _verify_scopes(
    ledger: ProjectionLedger,
    cq: ProjectionCQClient,
    scopes: tuple[ProjectionScope, ...],
) -> tuple[list[VerificationResult], list[ProjectionScope]]:
    """Core verification without lock. Returns (results, complete_scopes)."""
    results: list[VerificationResult] = []
    complete_scopes: list[ProjectionScope] = []
    clear_scopes: dict[str, list[str]] = {}
    for scope in scopes:
        expected_keys = ledger.expected_keys(scope)
        if expected_keys is None:
            results.append(
                VerificationResult(
                    "",
                    "",
                    scope,
                    [],
                    [],
                    False,
                    "scope has no expected-source marker",
                )
            )
            continue
        clear_scopes[scope.value] = expected_keys
        records = {record.key: record for record in ledger.records(scope)}
        scope_results: list[VerificationResult] = []
        for key in expected_keys:
            record = records.get(key)
            if record is None:
                source_path, fragment = key.split(":", 1)[1].split("#", 1)
                scope_results.append(
                    VerificationResult(
                        source_path,
                        fragment,
                        scope,
                        [],
                        [],
                        False,
                        "expected source has no ledger mapping",
                    )
                )
                continue
            found = cq.find_identity(record.identity_domain)
            matching = [
                ku_id
                for ku_id, unit in found.items()
                if record.marker in _unit_text(unit)
            ]
            valid = (
                not record.stale
                and len(found) == 1
                and matching == record.active_ku_ids
                and bool(record.active_ku_ids)
            )
            scope_results.append(
                VerificationResult(
                    record.source_path,
                    record.fragment,
                    scope,
                    record.active_ku_ids,
                    matching,
                    valid,
                    "valid"
                    if valid
                    else "CQ identity, KU ID, or content marker mismatch",
                )
            )
        results.extend(scope_results)
        if all(result.valid for result in scope_results):
            complete_scopes.append(scope)
    if clear_scopes:
        ledger.set_scope_expectations(clear_scopes)
    if complete_scopes:
        ledger.mark_scope_complete(tuple(complete_scopes))
    return results, complete_scopes


def verify(
    *, ledger: ProjectionLedger, cq: ProjectionCQClient, scopes: tuple[ProjectionScope, ...]
) -> list[VerificationResult]:
    """Validate every expected key, then atomically mark only valid scopes complete."""
    with ProjectionLock(ledger.path):
        if ledger.pending():
            raise ProjectionSafetyError("cannot verify while CQ operations are pending")
        results, _ = _verify_scopes(ledger, cq, scopes)
        return results


def _unit_text(unit: dict) -> str:
    """Render a CQ knowledge-unit dict as searchable text.

    CQ query results carry the meaningful fields inside an ``insight``
    sub-dict.  Older or synthetic units place them at the top level.
    This function handles both layouts with a single field list.
    """
    payload = unit.get("insight")
    if not isinstance(payload, dict):
        payload = unit
    return "\n".join(str(payload.get(key, "")) for key in ("summary", "detail", "action", "body"))
