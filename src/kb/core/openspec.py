"""OpenSpec durable archive reader.

Reads archived OpenSpec changes and standing specs from the store at
``~/.local/share/kb/openspec/<repo-slug>/``.  Each archived change has a
``kb-meta.yaml`` sidecar (``worktree``, ``branch``, ``date``, ``change``)
and a ``design.md`` document.  Standing specs live in
``specs/<spec-name>/spec.md`` per repo-slug.

This module is read-only — it never writes to the store.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

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
    except Exception:
        return None


def read_design_md(path: Path) -> str | None:
    """Read the full text of a *design.md* document.

    Returns ``None`` when the file is missing.
    """
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# OpenSpecStore — high-level query API
# ---------------------------------------------------------------------------

class OpenSpecStore:
    """Read-only accessor for the OpenSpec durable archive.

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

                # Apply date filter
                entry_date = meta.get("date")
                if entry_date:
                    try:
                        d = date.fromisoformat(entry_date)
                    except ValueError:
                        continue

                    if from_date:
                        try:
                            from_d = date.fromisoformat(from_date)
                        except ValueError:
                            continue
                        if d < from_d:
                            continue

                    if to_date:
                        try:
                            to_d = date.fromisoformat(to_date)
                        except ValueError:
                            continue
                        if d > to_d:
                            continue

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
        searched.  When multiple matches exist without a repo filter, returns
        ``None`` (ambiguous).
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
            # Ambiguous — caller should provide --repo
            return None
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
        except Exception:
            return None

        return {
            "repo": repo,
            "name": spec_name,
            "content": content,
        }
