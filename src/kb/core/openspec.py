"""OpenSpec durable archive reader.

Reads archived OpenSpec changes and standing specs from the store at
``~/.local/share/kb/openspec/<repo-slug>/``.  Each archived change has a
``kb-meta.yaml`` sidecar (``worktree``, ``branch``, ``date``, ``change``)
and a ``design.md`` document.  Standing specs live in
``specs/<spec-name>/spec.md`` per repo-slug.

This module reads and imports durable OpenSpec archives.
"""

from __future__ import annotations

from datetime import date, datetime
import hashlib
from pathlib import Path
import re
import subprocess
import tempfile

import yaml

from kb.config import resolve_kb_root

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OPENSPEC_SUBDIR = "openspec"
KB_META_FILENAME = "kb-meta.yaml"
DESIGN_FILENAME = "design.md"
SPEC_FILENAME = "spec.md"
ARCHIVES_DIR = "changes"
ARCHIVE_SUBDIR = "archive"
STATINGSPECS_DIR = "specs"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AmbiguousChangeError(Exception):
    """Raised when multiple archived changes share the same name."""

    def __init__(self, change_name: str, candidates: list[dict]) -> None:
        super().__init__(
            f"Ambiguous change name '{change_name}': "
            f"{len(candidates)} matches found. "
            "Specify --repo to disambiguate."
        )
        self.change_name = change_name
        self.candidates = candidates


class OpenSpecImportError(Exception):
    """Raised when an approved plan record cannot be imported."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def parse_kb_meta(path: Path) -> dict[str, str] | None:
    """Parse a *kb-meta.yaml* sidecar into a flat dict.

    Returns ``None`` when the file is missing or contains invalid YAML.
    """
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            return None
        return {k: str(v) for k, v in data.items()}
    except (yaml.YAMLError, OSError):
        return None


def read_design_md(path: Path) -> str | None:
    """Read the full text of a *design.md* document.

    Returns ``None`` when the file is missing.
    """
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _required_import_fields(record: object) -> dict[str, str]:
    if not isinstance(record, dict):
        raise OpenSpecImportError("invalid_record", "record must be a JSON object")

    fields = (
        "session_id",
        "worktree",
        "approval_time",
        "plan_content",
        "plan_sha256",
        "verified_implementation_evidence",
    )
    values: dict[str, str] = {}
    for field in fields:
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            raise OpenSpecImportError(
                "invalid_record", f"{field} must be a non-empty string"
            )
        values[field] = value
    return values


def _approved_plan_date(approval_time: str) -> str:
    if "T" not in approval_time:
        raise OpenSpecImportError(
            "invalid_approval_time", "approval_time must be an ISO-8601 timestamp"
        )
    try:
        normalized_time = (
            f"{approval_time[:-1]}+00:00"
            if approval_time.endswith("Z")
            else approval_time
        )
        return datetime.fromisoformat(normalized_time).date().isoformat()
    except ValueError as exc:
        raise OpenSpecImportError(
            "invalid_approval_time", "approval_time must be an ISO-8601 timestamp"
        ) from exc


def _change_name(plan_content: str) -> str:
    first_line = plan_content.split("\n", 1)[0].removesuffix("\r")
    match = re.fullmatch(r"#\s+(.+?)\s*#*", first_line)
    if match is None:
        raise OpenSpecImportError(
            "invalid_plan_content", "plan_content must begin with a Markdown H1"
        )
    change = re.sub(r"[^a-z0-9]+", "-", match.group(1).lower()).strip("-")
    if not change:
        raise OpenSpecImportError(
            "invalid_plan_content", "plan_content H1 must contain a usable change name"
        )
    return change


def _git_info(worktree: str) -> tuple[Path, str, str]:
    worktree_path = Path(worktree).expanduser().resolve()
    if not worktree_path.is_dir():
        raise OpenSpecImportError("invalid_worktree", "worktree must be an existing directory")

    try:
        common_dir = subprocess.run(
            [
                "git",
                "-C",
                str(worktree_path),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "-C", str(worktree_path), "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise OpenSpecImportError(
            "invalid_worktree", "worktree must be inside a Git repository"
        ) from exc

    common_path = Path(common_dir)
    repo_root = common_path.parent
    slug = repo_root.name.removesuffix(".git")
    if not slug:
        raise OpenSpecImportError(
            "invalid_worktree", "Git repository does not have a usable directory name"
        )
    return worktree_path, slug, branch


# ---------------------------------------------------------------------------
# OpenSpecStore — high-level query API
# ---------------------------------------------------------------------------

class OpenSpecStore:
    """Accessor for the OpenSpec durable archive.

    The store root is resolved from ``KB_ROOT`` (or the ``KB_OPENSPEC_ROOT``
    environment variable, for tests) by appending ``openspec`` to the parent
    directory.
    """

    def __init__(self, root: Path | None = None) -> None:
        if root is not None:
            self._root = root
        else:
            kb_root = resolve_kb_root(None, validate=False)
            self._root = kb_root / OPENSPEC_SUBDIR

    def _import_result(
        self, entry_path: Path, meta: dict[str, str], repo: str, created: bool
    ) -> dict[str, object]:
        return {
            "worktree": meta.get("worktree", ""),
            "branch": meta.get("branch", ""),
            "date": meta.get("date", ""),
            "change": meta.get("change", ""),
            "repo": repo,
            "path": str(entry_path),
            "session_id": meta.get("session_id", ""),
            "plan_sha256": meta.get("plan_sha256", ""),
            "created": created,
        }

    def _existing_import(
        self, archive_dir: Path, session_id: str, digest: str, repo: str
    ) -> dict[str, object] | None:
        if not archive_dir.is_dir():
            return None
        for entry_path in archive_dir.iterdir():
            if not entry_path.is_dir():
                continue
            meta = parse_kb_meta(entry_path / KB_META_FILENAME)
            if (
                meta is not None
                and meta.get("session_id") == session_id
                and meta.get("plan_sha256", "").lower() == digest
            ):
                return self._import_result(entry_path, meta, repo, created=False)
        return None

    def import_archive(self, record: object) -> dict[str, object]:
        """Persist one approved plan record and return its archive reference."""
        values = _required_import_fields(record)
        digest = values["plan_sha256"].lower()
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise OpenSpecImportError(
                "invalid_plan_sha256", "plan_sha256 must be a SHA-256 hexadecimal digest"
            )
        computed_digest = hashlib.sha256(
            values["plan_content"].encode("utf-8")
        ).hexdigest()
        if digest != computed_digest:
            raise OpenSpecImportError(
                "plan_sha256_mismatch", "plan_sha256 does not match plan_content"
            )

        approval_date = _approved_plan_date(values["approval_time"])
        change = _change_name(values["plan_content"])
        worktree, repo, branch = _git_info(values["worktree"])
        archive_dir = self._root / repo / ARCHIVES_DIR / ARCHIVE_SUBDIR
        entry_path = archive_dir / f"{approval_date}-{change}"

        try:
            existing = self._existing_import(
                archive_dir, values["session_id"], digest, repo
            )
            if existing is not None:
                return existing
            if entry_path.exists():
                raise OpenSpecImportError(
                    "archive_conflict",
                    f"archive already exists at {entry_path}",
                )

            metadata = {
                "worktree": str(worktree),
                "branch": branch,
                "date": approval_date,
                "change": change,
                "repo": repo,
                "session_id": values["session_id"],
                "approval_time": values["approval_time"],
                "plan_sha256": digest,
                "verified_implementation_evidence": values[
                    "verified_implementation_evidence"
                ],
            }
            archive_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix=".import-", dir=archive_dir
            ) as temp_dir:
                temp_path = Path(temp_dir)
                (temp_path / DESIGN_FILENAME).write_text(
                    values["plan_content"], encoding="utf-8"
                )
                (temp_path / KB_META_FILENAME).write_text(
                    yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
                temp_path.rename(entry_path)
        except OpenSpecImportError:
            raise
        except OSError as exc:
            meta = parse_kb_meta(entry_path / KB_META_FILENAME)
            if (
                meta is not None
                and meta.get("session_id") == values["session_id"]
                and meta.get("plan_sha256", "").lower() == digest
            ):
                return self._import_result(entry_path, meta, repo, created=False)
            raise OpenSpecImportError(
                "archive_write_failed",
                f"could not create archive at {entry_path}",
            ) from exc

        return self._import_result(entry_path, metadata, repo, created=True)

    # -- repo discovery -----------------------------------------------------

    def repo_slugs(self) -> list[str]:
        """Return every repo-slug directory under the store root."""
        if not self._root.is_dir():
            return []
        return sorted(
            d.name
            for d in self._root.iterdir()
            if d.is_dir()
        )

    # -- archive listing ----------------------------------------------------

    def list_archives(
        self,
        repo: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict]:
        """Return all archived changes, optionally filtered.

        Each entry is a dict with keys ``worktree``, ``branch``, ``date``,
        ``change``, ``repo``, and ``path`` (absolute path to the archive
        directory).  Results are sorted by ``date`` descending.
        """
        results: list[dict] = []

        # Parse date bounds once, up front
        from_d: date | None = None
        to_d: date | None = None
        if from_date:
            from_d = date.fromisoformat(from_date)
        if to_date:
            to_d = date.fromisoformat(to_date)

        has_date_filter = from_d is not None or to_d is not None

        repos = [repo] if repo else self.repo_slugs()
        for slug in repos:
            repo_dir = self._root / slug
            if not repo_dir.is_dir():
                continue

            archive_dir = repo_dir / ARCHIVES_DIR / ARCHIVE_SUBDIR
            if not archive_dir.is_dir():
                continue

            for entry_path in sorted(archive_dir.iterdir(), reverse=True):
                if not entry_path.is_dir():
                    continue

                meta = parse_kb_meta(entry_path / KB_META_FILENAME)
                if meta is None:
                    continue

                entry_date = meta.get("date")

                if has_date_filter:
                    # With a date filter, entries without a parseable date are excluded
                    if not entry_date:
                        continue
                    try:
                        d = date.fromisoformat(entry_date)
                    except ValueError:
                        continue

                    if from_d and d < from_d:
                        continue
                    if to_d and d > to_d:
                        continue
                else:
                    # No date filter — try to parse for sorting, but don't exclude
                    if entry_date:
                        try:
                            date.fromisoformat(entry_date)
                        except ValueError:
                            pass  # keep entry, sort will handle it

                results.append({
                    "worktree": meta.get("worktree", ""),
                    "branch": meta.get("branch", ""),
                    "date": meta.get("date", ""),
                    "change": meta.get("change", ""),
                    "repo": slug,
                    "path": str(entry_path),
                })

        # Sort by date descending
        results.sort(key=lambda e: e["date"], reverse=True)
        return results

    # -- archive detail -----------------------------------------------------

    def show_archive(
        self,
        change_name: str,
        repo: str | None = None,
    ) -> dict | None:
        """Return metadata + design for a single archived change.

        Looks up by the ``change`` field in *kb-meta.yaml*.  If *repo* is
        provided the search is scoped to that repo; otherwise all repos are
        searched.  Raises :class:`AmbiguousChangeError` when multiple matches
        exist without a repo filter.
        """
        candidates: list[dict] = []

        repos = [repo] if repo else self.repo_slugs()
        for slug in repos:
            repo_dir = self._root / slug
            if not repo_dir.is_dir():
                continue

            archive_dir = repo_dir / ARCHIVES_DIR / ARCHIVE_SUBDIR
            if not archive_dir.is_dir():
                continue

            for entry_path in archive_dir.iterdir():
                if not entry_path.is_dir():
                    continue

                meta = parse_kb_meta(entry_path / KB_META_FILENAME)
                if meta is None:
                    continue

                if meta.get("change") != change_name:
                    continue

                design = read_design_md(entry_path / DESIGN_FILENAME)
                candidates.append({
                    "meta": {
                        "worktree": meta.get("worktree", ""),
                        "branch": meta.get("branch", ""),
                        "date": meta.get("date", ""),
                        "change": meta.get("change", ""),
                        "repo": slug,
                    },
                    "design": design,
                })

        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise AmbiguousChangeError(change_name, candidates)
        return None

    # -- standing specs -----------------------------------------------------

    def list_specs(self, repo: str | None = None) -> list[dict]:
        """Return all standing specs, optionally filtered by repo.

        Each entry is a dict with keys ``repo``, ``name``, and ``path``.
        """
        results: list[dict] = []

        repos = [repo] if repo else self.repo_slugs()
        for slug in repos:
            repo_dir = self._root / slug
            if not repo_dir.is_dir():
                continue

            specs_dir = repo_dir / STATINGSPECS_DIR
            if not specs_dir.is_dir():
                continue

            for spec_dir in sorted(specs_dir.iterdir()):
                if not spec_dir.is_dir():
                    continue

                spec_file = spec_dir / SPEC_FILENAME
                if not spec_file.is_file():
                    continue

                results.append({
                    "repo": slug,
                    "name": spec_dir.name,
                    "path": str(spec_file),
                })

        return results

    def show_spec(
        self,
        spec_name: str,
        repo: str,
    ) -> dict | None:
        """Return a standing spec's content.

        Returns ``None`` when the spec or repo is not found.
        """
        repo_dir = self._root / repo
        if not repo_dir.is_dir():
            return None

        spec_file = repo_dir / STATINGSPECS_DIR / spec_name / SPEC_FILENAME
        if not spec_file.is_file():
            return None

        try:
            content = spec_file.read_text(encoding="utf-8")
        except OSError:
            return None

        return {
            "repo": repo,
            "name": spec_name,
            "content": content,
        }
