"""Atomic external ledger with recoverable CQ operation state."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from kb.cq.projection.models import (
    LEDGER_VERSION,
    LedgerRecord,
    PendingOperation,
    ProjectionScope,
    ScopeCompletion,
    utc_now,
)


class LedgerError(RuntimeError):
    pass


class ProjectionLedger:
    """External state. Every CQ mutation has a persisted pending transition."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self._records: dict[str, LedgerRecord] = {}
        self._pending: dict[str, PendingOperation] = {}
        self._scope_expectations: dict[str, list[str]] = {}
        self._backfill_complete_at: dict[str, str] = {}

    @classmethod
    def open(cls, path: Path) -> ProjectionLedger:
        ledger = cls(path)
        ledger.load()
        return ledger

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LedgerError(f"cannot read projection ledger: {exc}") from exc
        if payload.get("version") != LEDGER_VERSION:
            raise LedgerError("unsupported projection ledger version")
        self._records = {
            key: LedgerRecord.from_dict(value) for key, value in payload.get("records", {}).items()
        }
        self._pending = {
            key: PendingOperation.from_dict(value)
            for key, value in payload.get("pending", {}).items()
        }
        self._scope_expectations = {
            str(scope): list(keys) for scope, keys in payload.get("scope_expectations", {}).items()
        }
        self._backfill_complete_at = {
            str(scope): str(value)
            for scope, value in payload.get("backfill_complete_at", {}).items()
        }

    def save(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = {
            "version": LEDGER_VERSION,
            "records": {key: value.to_dict() for key, value in sorted(self._records.items())},
            "pending": {key: value.to_dict() for key, value in sorted(self._pending.items())},
            "scope_expectations": self._scope_expectations,
            "backfill_complete_at": self._backfill_complete_at,
        }
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".cq-projection-", dir=self.path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(payload, output, indent=2, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            temporary_path.chmod(0o600)
            temporary_path.replace(self.path)
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise LedgerError(f"cannot write projection ledger: {exc}") from exc

    def get(self, scope: ProjectionScope, source_path: str, fragment: str) -> LedgerRecord | None:
        return self._records.get(f"{scope.value}:{source_path}#{fragment}")

    def put(self, record: LedgerRecord) -> None:
        self._records[record.key] = record

    def records(self, scope: ProjectionScope | None = None) -> list[LedgerRecord]:
        values = self._records.values()
        if scope is not None:
            values = (record for record in values if record.scope is scope)
        return sorted(values, key=lambda record: record.key)

    def pending(self) -> list[PendingOperation]:
        return sorted(self._pending.values(), key=lambda item: item.key)

    def put_pending(self, pending: PendingOperation) -> None:
        self._pending[pending.key] = pending
        self.save()

    def remove_pending(self, pending: PendingOperation) -> None:
        self._pending.pop(pending.key, None)
        self.save()

    def set_scope_expectations(self, expectations: dict[str, list[str]]) -> None:
        for scope, keys in expectations.items():
            self._scope_expectations[scope] = sorted(keys)
            self._backfill_complete_at.pop(scope, None)
        self.save()

    def expected_keys(self, scope: ProjectionScope) -> list[str] | None:
        keys = self._scope_expectations.get(scope.value)
        return None if keys is None else list(keys)

    def mark_scope_complete(self, scopes: tuple[ProjectionScope, ...]) -> None:
        for scope in scopes:
            if scope.value not in self._scope_expectations:
                raise LedgerError(f"scope has no expected-source marker: {scope.value}")
            self._backfill_complete_at[scope.value] = utc_now()
        self.save()

    def completions(self) -> list[ScopeCompletion]:
        result: list[ScopeCompletion] = []
        for scope in ProjectionScope:
            expected_keys = self._scope_expectations.get(scope.value)
            expected = len(expected_keys) if expected_keys is not None else 0
            records = {record.key: record for record in self.records(scope)}
            active = sum(
                key in records and bool(records[key].active_ku_ids) and not records[key].stale
                for key in expected_keys or []
            )
            stale = sum(records[key].stale for key in expected_keys or [] if key in records)
            complete_at = self._backfill_complete_at.get(scope.value)
            result.append(
                ScopeCompletion(
                    scope=scope,
                    expected=expected,
                    active=active,
                    stale=stale,
                    backfill_complete_at=complete_at,
                    complete=complete_at is not None and active == expected and stale == 0,
                )
            )
        return result
