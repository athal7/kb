"""Supported CQ CLI adapter. It never opens CQ SQLite directly."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from kb.cq.projection.models import ProjectionSource
from kb.cq.projection.safety import require_clean_cq_status


class CQCommandError(RuntimeError):
    pass


class CQCli:
    """CQ CLI adapter. Delegates to the cq executable."""

    def __init__(
        self,
        *,
        executable: str = "cq",
        runner=subprocess.run,
    ) -> None:
        candidate = Path(executable)
        resolved = candidate if candidate.is_absolute() else Path(shutil.which(executable) or "")
        if not resolved.is_absolute() or not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise CQCommandError(f"cannot locate executable cq: {executable}")
        self.executable = str(resolved.resolve())
        self.runner = runner

    def status(self) -> dict[str, Any]:
        status = self._run("status", "--format", "json")
        require_clean_cq_status(status)
        return status

    def propose(self, source: ProjectionSource) -> str:
        arguments = [
            "propose",
            "--format",
            "json",
            "--summary",
            source.summary,
            "--detail",
            source.detail + "\n\n" + source.marker,
            "--action",
            source.action,
        ]
        for domain in source.domains:
            arguments.extend(("--domain", domain))
        response = self._run(*arguments)
        ku_id = _first_id(response)
        if ku_id is None:
            raise CQCommandError("cq propose did not return a KU ID")
        return ku_id

    def stale(self, ku_id: str) -> None:
        self._run("flag", ku_id, "--reason", "stale")

    def find_identity(self, identity_domain: str) -> dict[str, dict[str, Any]]:
        records = _records(
            self._run(
                "query",
                "--format",
                "json",
                "--domain",
                identity_domain,
                "--limit",
                "50",
            )
        )
        if len(records) == 50:
            raise CQCommandError("identity query reached CQ result limit; retrieval is incomplete")
        return {ku_id: record for record in records if (ku_id := _first_id(record)) is not None}

    def _run(self, *arguments: str) -> Any:
        command = [self.executable, *arguments]
        try:
            completed = self.runner(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise CQCommandError(f"cannot execute cq: {exc}") from exc
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise CQCommandError(f"cq command failed: {message}")
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise CQCommandError("cq command returned non-JSON output") from exc


def _first_id(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in ("id", "ku_id", "unit_id"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate
    for key in ("data", "unit", "knowledge_unit"):
        candidate = _first_id(value.get(key))
        if candidate is not None:
            return candidate
    return None


def _records(value: Any) -> Sequence[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    for key in ("results", "data", "units", "knowledge_units"):
        candidate = value.get(key)
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    return [value]
