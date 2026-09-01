"""Advisory single-run lock for projection apply and recovery."""

from __future__ import annotations

import fcntl
from pathlib import Path


class ProjectionLockError(RuntimeError):
    pass


class ProjectionLock:
    def __init__(self, ledger_path: Path) -> None:
        self.path = ledger_path.with_suffix(ledger_path.suffix + ".lock")
        self._file = None

    def __enter__(self) -> ProjectionLock:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._file = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._file.close()
            self._file = None
            raise ProjectionLockError("a CQ projection run is already active") from exc
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._file is not None:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            self._file.close()
            self._file = None
