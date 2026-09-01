"""Deterministic, non-mutating focused fact planning from canonical KB files."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from kb.core.frontmatter import split
from kb.cq.projection.ledger import ProjectionLedger
from kb.cq.projection.models import (
    AccessClassification,
    ProjectionAction,
    ProjectionManifest,
    ProjectionOperation,
    ProjectionScope,
    ProjectionSource,
)
from kb.cq.projection.safety import (
    access_classification,
    require_access_authorization,
    require_no_source_secrets,
)


class ProjectionPlanError(RuntimeError):
    pass


_DEFAULT_ACCESS = {
    ProjectionScope.PEOPLE: AccessClassification("internal"),
    ProjectionScope.PROJECTS: AccessClassification("internal"),
    ProjectionScope.PRODUCTS: AccessClassification("internal"),
    ProjectionScope.DECISIONS: AccessClassification("internal"),
    ProjectionScope.STANDING: AccessClassification("internal"),
}
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_MAX_FACT_CHARS = 7_000
_MAX_SUMMARY_CHARS = 500
_MAX_DETAIL_CHARS = 8_000
_MAX_ACTION_CHARS = 2_000
_MAX_DOMAINS = 16
_MAX_DOMAIN_CHARS = 64


def sources_for_scopes(
    kb_root: Path,
    scopes: tuple[ProjectionScope, ...],
    authorization_policy: str | None,
) -> dict[str, ProjectionSource]:
    """Rebuild canonical fact units for apply-time manifest validation."""
    return {
        source.key: source
        for scope in scopes
        for source in _sources_for_scope(kb_root, scope, authorization_policy)
    }


def build_plan(
    *,
    kb_root: Path,
    ledger: ProjectionLedger,
    target_db: Path,
    authorization_policy: str | None,
    scopes: tuple[ProjectionScope, ...],
) -> ProjectionManifest:
    """Create an unapproved plan. This does not mutate KB, CQ, or ledger."""
    sources = sources_for_scopes(kb_root, scopes, authorization_policy)
    operations: list[ProjectionOperation] = []
    for key, source in sorted(sources.items()):
        record = ledger.get(source.scope, source.source_path, source.fragment)
        if record is None:
            action, previous, reason = ProjectionAction.CREATE, [], "source has no ledger mapping"
        elif record.source_fingerprint != source.fingerprint or record.stale:
            action, previous, reason = (
                ProjectionAction.REPLACE,
                record.active_ku_ids,
                "source changed",
            )
        else:
            action, previous, reason = (
                ProjectionAction.UNCHANGED,
                record.active_ku_ids,
                "source matches",
            )
        operations.append(ProjectionOperation(action, source, previous, reason))

    expected = {
        scope.value: sorted(source.key for source in sources.values() if source.scope is scope)
        for scope in scopes
    }
    for record in ledger.records():
        if record.scope not in scopes or record.key in sources or not record.active_ku_ids:
            continue
        source = ProjectionSource(
            scope=record.scope,
            source_path=record.source_path,
            fragment=record.fragment,
            fingerprint=record.source_fingerprint,
            classification=record.classification,
            entity_name=record.source_path,
            aliases=[],
            summary=record.source_path,
            detail="Canonical KB source was removed.",
            action="Remove obsolete local index entry.",
            domains=[record.identity_domain],
            identity_domain=record.identity_domain,
            marker=record.marker,
        )
        operations.append(
            ProjectionOperation(
                ProjectionAction.STALE, source, record.active_ku_ids, "source removed"
            )
        )
    return ProjectionManifest(
        target_db=str(target_db),
        authorization_policy=authorization_policy,
        scope_expectations=expected,
        operations=operations,
    )


def _sources_for_scope(
    kb_root: Path, scope: ProjectionScope, authorization_policy: str | None
) -> list[ProjectionSource]:
    return [
        source
        for path in _scope_paths(kb_root, scope)
        for source in _sources_from_file(kb_root, path, scope, authorization_policy)
    ]


def _sources_from_file(
    kb_root: Path, path: Path, scope: ProjectionScope, authorization_policy: str | None
) -> list[ProjectionSource]:
    raw = path.read_text(encoding="utf-8")
    require_no_source_secrets(raw)
    parsed = split(raw)
    metadata = parsed.frontmatter or {}
    classification = access_classification(metadata, _DEFAULT_ACCESS[scope])
    require_access_authorization(classification, authorization_policy)
    body = parsed.body.strip()
    name = _title(body, path.stem)
    aliases = _aliases(metadata)
    relative = path.relative_to(kb_root).as_posix()
    return [
        _source(
            scope=scope,
            source_path=relative,
            fragment=fragment,
            content=content,
            classification=classification,
            entity_name=name,
            aliases=aliases,
        )
        for fragment, content in _fragments(body)
    ]


def _source(
    *,
    scope: ProjectionScope,
    source_path: str,
    fragment: str,
    content: str,
    classification: AccessClassification,
    entity_name: str,
    aliases: list[str],
) -> ProjectionSource:
    identity = hashlib.sha256(f"{scope}:{source_path}:{fragment}".encode()).hexdigest()[:24]
    fingerprint = hashlib.sha256(content.encode()).hexdigest()
    identity_domain = f"kb-id-{identity}"
    marker = f"kb-projection:{identity}:{fingerprint}"
    summary = _truncate(f"KB {scope.value}: {entity_name} — {fragment}", _MAX_SUMMARY_CHARS)
    action = _truncate(
        f"Use this canonical KB {scope.value} fact for local context.",
        _MAX_ACTION_CHARS,
    )
    detail = _truncate(content, _MAX_DETAIL_CHARS - len(marker) - 2)
    domains = _domains(identity_domain, scope, entity_name, aliases)
    _validate_cq_limits(summary, detail, action, domains, marker)
    return ProjectionSource(
        scope=scope,
        source_path=source_path,
        fragment=fragment,
        fingerprint=fingerprint,
        classification=classification,
        entity_name=entity_name,
        aliases=aliases,
        summary=summary,
        detail=detail,
        action=action,
        domains=domains,
        identity_domain=identity_domain,
        marker=marker,
    )


def _scope_paths(kb_root: Path, scope: ProjectionScope) -> list[Path]:
    if scope is ProjectionScope.STANDING:
        return [
            path
            for path in (
                kb_root / "standing.md",
                kb_root / "status.md",
                kb_root / "action-items.md",
            )
            if path.is_file()
        ]
    directory = kb_root / scope.value
    return sorted(directory.glob("*.md")) if directory.is_dir() else []


def _fragments(body: str) -> list[tuple[str, str]]:
    matches = [match for match in _HEADING.finditer(body) if len(match.group(1)) >= 2]
    if not matches:
        sections = [("overview", body)]
    else:
        sections = []
        prefix = body[: matches[0].start()].strip()
        if prefix:
            sections.append(("overview", prefix))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
            sections.append((match.group(2), body[match.start() : end].strip()))
    return [
        (f"{_fragment_name(heading)}-{part}", chunk)
        for heading, section in sections
        for part, chunk in enumerate(_chunk(section), start=1)
        if chunk
    ]


def _chunk(text: str) -> list[str]:
    if len(text) <= _MAX_FACT_CHARS:
        return [text]
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        if len(paragraph) > _MAX_FACT_CHARS:
            for start in range(0, len(paragraph), _MAX_FACT_CHARS):
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(paragraph[start : start + _MAX_FACT_CHARS])
        elif current and len(current) + len(paragraph) + 2 > _MAX_FACT_CHARS:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}".strip()
    if current:
        chunks.append(current)
    return chunks


def _aliases(metadata: dict) -> list[str]:
    value = metadata.get("aliases", [])
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _title(text: str, fallback: str) -> str:
    match = _HEADING.search(text)
    return match.group(2) if match else fallback


def _fragment_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "fact"


def _domains(
    identity_domain: str,
    scope: ProjectionScope,
    name: str,
    aliases: list[str],
) -> list[str]:
    domains = [identity_domain, f"kb-scope-{scope.value}"]
    for value in [name, *aliases]:
        token = _truncate(_fragment_name(value), _MAX_DOMAIN_CHARS)
        name_token = _truncate(f"kb-name-{token}", _MAX_DOMAIN_CHARS)
        domains.extend((token, name_token))
    return list(dict.fromkeys(domains))[:_MAX_DOMAINS]


def _truncate(value: str, limit: int) -> str:
    return value[:limit]


def _validate_cq_limits(
    summary: str,
    detail: str,
    action: str,
    domains: list[str],
    marker: str,
) -> None:
    if len(summary) > _MAX_SUMMARY_CHARS:
        raise ProjectionPlanError("generated CQ summary exceeds limit")
    if len(detail) + len(marker) + 2 > _MAX_DETAIL_CHARS:
        raise ProjectionPlanError("generated CQ detail exceeds limit")
    if len(action) > _MAX_ACTION_CHARS:
        raise ProjectionPlanError("generated CQ action exceeds limit")
    if len(domains) > _MAX_DOMAINS or any(len(domain) > _MAX_DOMAIN_CHARS for domain in domains):
        raise ProjectionPlanError("generated CQ domains exceed limit")
