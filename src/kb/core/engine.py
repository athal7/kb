"""The KB Engine library.

Deterministic core implementing the Contract's query operation and atomic writes
with invariant checks (section caps, relationship symmetry, alias/map sync).
"""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from kb.contract.envelope import ContractResponse, ErrorResponse, SuccessResponse
from kb.contract.errors import ContractError
from kb.contract.query import QueryHit, QueryRequest, QueryResult
from kb.contract.schema_pack import Document, Profile, Relationship
from kb.contract.translate import person_to_profile, product_to_profile, project_to_profile
from kb.core.index import VaultIndex
from kb.core.models import EntityKind


def _fold(name: str) -> str:
    return name.strip().casefold()


def get_inverse_relationship(kind: str, rel_name: str) -> tuple[str, str] | None:
    """Returns (inverse_kind, inverse_rel_name) for bidirectional relationship sync."""
    if kind == "person" and rel_name == "projects":
        return "project", "people"
    if kind == "project" and rel_name == "people":
        return "person", "projects"
    if kind == "project" and rel_name == "product":
        return "product", "projects"
    if kind == "product" and rel_name == "projects":
        return "project", "product"
    return None


def get_map_filename(kind: str) -> str | None:
    """Returns the JSON resolution map file name for a profile kind."""
    if kind == "person":
        return "names.json"
    if kind == "project":
        return "projects.json"
    if kind == "product":
        return "product-labels.json"
    return None


_KIND_TO_PLURAL = {
    "person": "people",
    "project": "projects",
    "product": "products",
}


class Engine:
    """Deterministic KB engine library owning all invariants and queries."""

    def __init__(self, kb_root: Path) -> None:
        self.kb_root = kb_root
        self._index = VaultIndex.build(kb_root)

    def reload(self) -> None:
        """Re-scan the vault to ensure the index is fully in-sync."""
        self._index = VaultIndex.build(self.kb_root)

    def query(self, request: QueryRequest) -> ContractResponse[QueryResult]:
        """Expose a query/search operation across profiles and documents."""
        if request.limit is not None and request.limit < 0:
            return ErrorResponse(
                error=ContractError.validation(
                    path="/limit",
                    message="Limit parameter must be non-negative.",
                    code="validation.invariant"
                )
            )
        try:
            hits: list[QueryHit] = []
            query_warnings: list[ContractWarning] = []

            # 1. Collect all Profiles
            profiles: list[Profile] = []
            for p in self._index.all_people():
                profiles.append(person_to_profile(p, self._index))
            for pr in self._index.all_projects():
                profiles.append(project_to_profile(pr, self._index))
            for prod in self._index.all_products():
                profiles.append(product_to_profile(prod, self._index))

            # 2. Collect all Documents
            documents: list[Document] = []
            # Journal
            for j in self._index.journal_entries():
                body_parts = []
                for s in j.sections:
                    if s.heading:
                        body_parts.append(f"## {s.heading}")
                    body_parts.append(s.body)
                body = f"# {j.date}\n" + "\n".join(body_parts)
                documents.append(
                    Document(
                        namespace="journal",
                        kind="journal",
                        body=body,
                        provenance={"date": j.date, "ref": f"journal/{j.date}"}
                    )
                )
            # Decisions
            for d in self._index.decisions():
                body_parts = []
                for s in d.sections:
                    if s.heading:
                        body_parts.append(f"## {s.heading}")
                    body_parts.append(s.body)
                body = "\n".join(body_parts)
                dec_slug = PurePosixPath(d.file).with_suffix("").name
                documents.append(
                    Document(
                        namespace="decisions",
                        kind="decision",
                        body=body,
                        provenance={
                            "is_readonly": d.is_readonly,
                            "file": d.file,
                            "ref": f"decisions/{dec_slug}",
                        }
                    )
                )
            # Openspec specs (under kb_root/openspec recursively if exists)
            openspec_dir = self.kb_root / "openspec"
            if openspec_dir.is_dir():
                for md_file in sorted(openspec_dir.rglob("*.md")):
                    try:
                        content = md_file.read_text(encoding="utf-8")
                        rel_path = md_file.relative_to(self.kb_root).as_posix()
                        spec_slug = PurePosixPath(rel_path).with_suffix("").as_posix()
                        documents.append(
                            Document(
                                namespace="openspec",
                                kind="spec",
                                body=content,
                                provenance={"path": rel_path, "ref": f"openspec/{spec_slug}"}
                            )
                        )
                    except Exception as e:
                        from kb.contract.envelope import ContractWarning
                        query_warnings.append(
                            ContractWarning(
                                code="io.read_failure",
                                message=f"Failed to read/decode OpenSpec file '{md_file}': {e}"
                            )
                        )

            # 3. Match Profiles
            for profile in profiles:
                # Scoping
                if request.collections:
                    # Plural name match
                    plural_kind = _KIND_TO_PLURAL.get(profile.kind, f"{profile.kind}s")
                    if plural_kind not in request.collections:
                        continue

                # Relationship traversal
                if request.related_to:
                    rel_matched = False
                    # Check if profile has relationship pointing to related_to
                    for rel in profile.relationships:
                        if rel.target.lower() == request.related_to.lower():
                            if (
                                not request.relationship
                                or rel.name.lower() == request.relationship.lower()
                            ):
                                rel_matched = True
                                break
                    # Check if starting profile has relationship pointing to this candidate
                    if not rel_matched:
                        starting_ref = request.related_to
                        # Find starting profile
                        starting_profile = next(
                            (p for p in profiles if p.ref.lower() == starting_ref.lower()),
                            None,
                        )
                        if starting_profile:
                            for rel in starting_profile.relationships:
                                if rel.target.lower() == profile.ref.lower():
                                    if (
                                        not request.relationship
                                        or rel.name.lower() == request.relationship.lower()
                                    ):
                                        rel_matched = True
                                        break
                    if not rel_matched:
                        continue

                # Field-level filters
                filter_failed = False
                for flt in request.filters:
                    if flt.field not in profile.fields:
                        filter_failed = True
                        break
                    val = profile.fields[flt.field]
                    if not self._evaluate_filter(val, flt.op, flt.value):
                        filter_failed = True
                        break
                if filter_failed:
                    continue

                # Text/substring search
                if request.text:
                    text_matched = False
                    matched_in = ""
                    snippet = ""

                    # Alias-aware resolution
                    # Check if query matches alias-aware resolution
                    for k in [EntityKind.PERSON, EntityKind.PROJECT, EntityKind.PRODUCT]:
                        res = self._index.resolve_wikilink(request.text, k)
                        if res.entity and res.entity.file:
                            canonical_ref = (
                                PurePosixPath(res.entity.file).with_suffix("").as_posix()
                            )
                            if canonical_ref.lower() == profile.ref.lower():
                                text_matched = True
                                matched_in = "resolution-map"
                                snippet = f"Matched via alias-aware resolution of '{request.text}'"
                                break
                    if text_matched:
                        hits.append(
                            QueryHit(
                                ref=profile.ref,
                                collection=_KIND_TO_PLURAL.get(profile.kind, f"{profile.kind}s"),
                                snippet=snippet,
                                matched_in=matched_in,
                                related_refs=[r.target for r in profile.relationships]
                            )
                        )
                        continue

                    # Direct text search in ref/kind
                    if request.text.lower() in profile.ref.lower():
                        text_matched = True
                        matched_in = "ref"
                        snippet = profile.ref
                    elif request.text.lower() in profile.kind.lower():
                        text_matched = True
                        matched_in = "kind"
                        snippet = profile.kind

                    # Direct text search in fields
                    if not text_matched:
                        for f_key, f_val in profile.fields.items():
                            if request.text.lower() in str(f_val).lower():
                                text_matched = True
                                matched_in = f"fields.{f_key}"
                                snippet = str(f_val)
                                break

                    # Direct text search in sections
                    if not text_matched:
                        for sec in profile.sections:
                            if sec.heading and request.text.lower() in sec.heading.lower():
                                text_matched = True
                                matched_in = f"sections.{sec.heading}"
                                snippet = sec.body[:150]
                                break
                            # Check line-by-line for high-fidelity snippet
                            for line in sec.body.split("\n"):
                                if request.text.lower() in line.lower():
                                    text_matched = True
                                    matched_in = f"sections.{sec.heading or 'body'}"
                                    snippet = line.strip()
                                    break
                            if text_matched:
                                break

                    if not text_matched:
                        continue

                    hits.append(
                        QueryHit(
                            ref=profile.ref,
                            collection=_KIND_TO_PLURAL.get(profile.kind, f"{profile.kind}s"),
                            snippet=snippet,
                            matched_in=matched_in,
                            related_refs=[r.target for r in profile.relationships]
                        )
                    )
                else:
                    # No text search parameter -> match all that pass filters/scoping/relationships
                    hits.append(
                        QueryHit(
                            ref=profile.ref,
                            collection=_KIND_TO_PLURAL.get(profile.kind, f"{profile.kind}s"),
                            snippet=profile.ref,
                            matched_in="ref",
                            related_refs=[r.target for r in profile.relationships]
                        )
                    )

            # 4. Match Documents
            for doc in documents:
                # Documents cannot have relationship traversal queries
                if request.related_to:
                    continue

                # Scoping
                if request.collections:
                    if doc.namespace not in request.collections:
                        continue

                # Field-level filters (on provenance)
                filter_failed = False
                for flt in request.filters:
                    if flt.field not in doc.provenance:
                        filter_failed = True
                        break
                    val = doc.provenance[flt.field]
                    if not self._evaluate_filter(val, flt.op, flt.value):
                        filter_failed = True
                        break
                if filter_failed:
                    continue

                # Text/substring search
                if request.text:
                    text_matched = False
                    matched_in = ""
                    snippet = ""

                    if request.text.lower() in doc.namespace.lower():
                        text_matched = True
                        matched_in = "namespace"
                        snippet = doc.namespace
                    elif request.text.lower() in doc.kind.lower():
                        text_matched = True
                        matched_in = "kind"
                        snippet = doc.kind

                    if not text_matched:
                        for p_key, p_val in (doc.provenance or {}).items():
                            if request.text.lower() in str(p_val).lower():
                                text_matched = True
                                matched_in = f"provenance.{p_key}"
                                snippet = str(p_val)
                                break

                    if not text_matched:
                        for line in doc.body.split("\n"):
                            if request.text.lower() in line.lower():
                                text_matched = True
                                matched_in = "body"
                                snippet = line.strip()
                                break

                    if not text_matched:
                        continue

                    doc_ref = (doc.provenance or {}).get("ref") or doc.namespace
                    hits.append(
                        QueryHit(
                            ref=doc_ref,
                            collection=doc.namespace,
                            snippet=snippet,
                            matched_in=matched_in,
                            related_refs=[]
                        )
                    )
                else:
                    # No text search parameter
                    doc_ref = (doc.provenance or {}).get("ref") or doc.namespace
                    hits.append(
                        QueryHit(
                            ref=doc_ref,
                            collection=doc.namespace,
                            snippet=doc.body[:150].strip(),
                            matched_in="body",
                            related_refs=[]
                        )
                    )

            # Limit/truncation
            total = len(hits)
            truncated = False
            if request.limit is not None and request.limit < total:
                hits = hits[:request.limit]
                truncated = True

            return SuccessResponse[QueryResult](
                warnings=query_warnings,
                data=QueryResult(hits=hits, total=total, truncated=truncated)
            )

        except Exception as e:
            return ErrorResponse(
                error=ContractError.io(
                    path="",
                    message=f"Transient query error: {e}"
                )
            )

    def _evaluate_filter(self, entity_val: Any, op: str, filter_val: Any) -> bool:
        try:
            if op == "=":
                return str(entity_val).lower() == str(filter_val).lower()
            if op == "!=":
                return str(entity_val).lower() != str(filter_val).lower()
            if op == "contains":
                if isinstance(entity_val, list):
                    return any(str(filter_val).lower() in str(x).lower() for x in entity_val)
                return str(filter_val).lower() in str(entity_val).lower()

            # Numeric/date comparisons
            # Convert values to floats if possible, or dates, or strings
            try:
                ev = float(entity_val)
                fv = float(filter_val)
            except ValueError:
                ev = str(entity_val)
                fv = str(filter_val)

            if op == ">":
                return ev > fv
            if op == "<":
                return ev < fv
            if op == ">=":
                return ev >= fv
            if op == "<=":
                return ev <= fv
        except Exception:
            return False
        return False

    def write_profile(self, profile: Profile) -> ContractResponse[None]:
        """Perform an atomic validated write of a Profile, maintaining all invariants."""
        # --- Pre-commit Validation ---
        # 1. Section caps: 'Current' section has at most 5 items
        import re
        bullet_pattern = re.compile(r"^\s*([\-*+]|\d+[\.)])(\s|$)")
        for sec in profile.sections:
            if sec.heading and sec.heading.lower() == "current":
                bullets = [line for line in sec.body.split("\n") if bullet_pattern.match(line)]
                if len(bullets) > 5:
                    return ErrorResponse(
                        error=ContractError.validation(
                            path="/sections",
                            message="Section 'Current' has exceeded the cap of 5 items.",
                            code="validation.section_cap"
                        )
                    )

        # 2. Derive Slug if not specified in ref
        slug = profile.ref.split("/")[-1] if profile.ref else ""
        if not slug:
            # Generate slug from title or display name
            title = profile.fields.get("name") or ""
            if not title:
                for sec in profile.sections:
                    if sec.heading:
                        title = sec.heading
                        break
            if not title:
                return ErrorResponse(
                    error=ContractError.validation(
                        path="/ref",
                        message=(
                            "Cannot save Profile: ref slug is empty and "
                            "could not be derived from title"
                        ),
                        code="validation.invariant"
                    )
                )
            import re
            # Basic cleanup to form a candidate slug
            slug = re.sub(r"[^a-zA-Z0-9\-]", "-", title.strip().lower()).replace(" ", "-")
            slug = re.sub(r"-+", "-", slug).strip("-")
            plural = _KIND_TO_PLURAL.get(profile.kind, f"{profile.kind}s")
            profile.ref = f"{plural}/{slug}"

        # Validate slug safety and path traversal
        plural = _KIND_TO_PLURAL.get(profile.kind, f"{profile.kind}s")
        collection_dir = (self.kb_root / plural).resolve()
        import re
        if not re.match(r"^[a-z0-9\-]+$", slug):
            return ErrorResponse(
                error=ContractError.validation(
                    path="/ref",
                    message=(
                        f"Invalid slug characters in '{slug}'. Only lowercase "
                        "letters, numbers, and hyphens are allowed."
                    ),
                    code="validation.invariant"
                )
            )

        self_file_path = (collection_dir / f"{slug}.md").resolve()
        try:
            self_file_path.relative_to(collection_dir)
        except ValueError:
            return ErrorResponse(
                error=ContractError.validation(
                    path="/ref",
                    message="Path traversal detected or file is outside the collection directory.",
                    code="validation.invariant"
                )
            )

        # 3. Simulate and gather all writes
        # To make it atomic, we compute all file updates in-memory and write them all together.
        files_to_write: dict[Path, str] = {}

        # Self markdown
        self_md_content = self._serialize_profile_to_markdown(profile, slug)
        files_to_write[self_file_path] = self_md_content

        # Bidirectional relationship sync
        # Compare old relationships in the index with new relationships in the profile
        old_relationships: list[Relationship] = []
        old_profile = self._get_indexed_profile(profile.ref)
        if old_profile:
            old_relationships = old_profile.relationships

        # New relationships targets and names
        new_rels = {(rel.name, rel.target) for rel in profile.relationships}
        old_rels = {(rel.name, rel.target) for rel in old_relationships}

        added_rels = new_rels - old_rels
        removed_rels = old_rels - new_rels

        # Track loaded target profiles in memory so we update them correctly
        # if they are modified multiple times
        loaded_targets: dict[str, Profile] = {}

        def get_or_load_profile(ref: str) -> Profile | None:
            if ref in loaded_targets:
                return loaded_targets[ref]
            p = self._get_indexed_profile(ref)
            if p:
                loaded_targets[ref] = p
                return p
            return None

        # Process removals
        for rel_name, rel_target in removed_rels:
            inv = get_inverse_relationship(profile.kind, rel_name)
            if inv:
                inv_kind, inv_name = inv
                target_profile = get_or_load_profile(rel_target)
                if target_profile:
                    # Filter out relationship pointing back to profile.ref
                    target_profile.relationships = [
                        r for r in target_profile.relationships
                        if not (r.name == inv_name and r.target.lower() == profile.ref.lower())
                    ]

        # Process additions
        for rel_name, rel_target in added_rels:
            inv = get_inverse_relationship(profile.kind, rel_name)
            if inv:
                inv_kind, inv_name = inv
                target_profile = get_or_load_profile(rel_target)
                if not target_profile:
                    return ErrorResponse(
                        error=ContractError.validation(
                            path="/relationships",
                            message=f"Target profile '{rel_target}' not found.",
                            code="validation.invariant"
                        )
                    )
                if target_profile.kind != inv_kind:
                    return ErrorResponse(
                        error=ContractError.validation(
                            path="/relationships",
                            message=(
                                f"Target profile '{rel_target}' has kind "
                                f"'{target_profile.kind}', expected '{inv_kind}'."
                            ),
                            code="validation.invariant"
                        )
                    )
                # Add relationship pointing back to profile.ref if not exists
                exists = any(
                    r.name == inv_name and r.target.lower() == profile.ref.lower()
                    for r in target_profile.relationships
                )
                if not exists:
                    target_profile.relationships.append(
                        Relationship(name=inv_name, target=profile.ref)
                    )

        # Re-serialize modified target profiles
        for target_ref, target_p in loaded_targets.items():
            t_slug = target_ref.split("/")[-1]
            t_md = self._serialize_profile_to_markdown(target_p, t_slug)
            t_plural = _KIND_TO_PLURAL.get(target_p.kind, f"{target_p.kind}s")
            t_dir = (self.kb_root / t_plural).resolve()
            t_file_path = (t_dir / f"{t_slug}.md").resolve()
            try:
                t_file_path.relative_to(t_dir)
            except ValueError:
                return ErrorResponse(
                    error=ContractError.validation(
                        path="/relationships",
                        message="Path traversal detected on target relationship profile.",
                        code="validation.invariant"
                    )
                )
            files_to_write[t_file_path] = t_md

        # Alias/resolution-map sync
        map_filename = get_map_filename(profile.kind)
        if map_filename:
            map_path = self.kb_root / map_filename
            map_data: dict[str, str] = {}
            if map_path.is_file():
                try:
                    map_data = json.loads(map_path.read_text(encoding="utf-8"))
                except Exception as e:
                    return ErrorResponse(
                        error=ContractError.validation(
                            path=f"/{map_filename}",
                            message=f"Malformed resolution map JSON: {e}",
                            code="validation.invariant"
                        )
                    )

            # Find display name or slug of profile to use as target
            title = profile.fields.get("name") or ""
            if not title:
                for sec in profile.sections:
                    if sec.heading:
                        title = sec.heading
                        break
            canonical_target = title or slug

            # New aliases list
            new_aliases = profile.fields.get("aliases", [])
            # Convert to list of strings
            if isinstance(new_aliases, list):
                new_aliases = [str(a) for a in new_aliases]
            else:
                new_aliases = []

            # Sync aliases in the map:
            # 1. Remove keys mapping to this canonical_target if they are no longer in new_aliases
            keys_to_remove = []
            for k, v in map_data.items():
                if v == canonical_target or v == slug:
                    if k not in new_aliases:
                        keys_to_remove.append(k)
            for k in keys_to_remove:
                del map_data[k]

            # 2. Add/set new aliases mapping to this canonical_target
            for alias in new_aliases:
                map_data[alias] = canonical_target

            # Save map
            files_to_write[map_path] = json.dumps(map_data, indent=2) + "\n"

        # --- Commit All Changes Atomically ---
        try:
            # First write to temp files, then rename to make it fully atomic
            written_temp_paths: list[tuple[Path, Path]] = []
            for final_path, content in files_to_write.items():
                final_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = final_path.with_suffix(f"{final_path.suffix}.tmp")
                temp_path.write_text(content, encoding="utf-8")
                written_temp_paths.append((temp_path, final_path))

            # Store original state for rollback journal
            original_contents: dict[Path, str | None] = {}
            for temp_path, final_path in written_temp_paths:
                if final_path.is_file():
                    original_contents[final_path] = final_path.read_text(encoding="utf-8")
                else:
                    original_contents[final_path] = None

            successful_renames: list[Path] = []
            try:
                for temp_path, final_path in written_temp_paths:
                    os.replace(temp_path, final_path)
                    successful_renames.append(final_path)
            except Exception as commit_err:
                # Rollback transaction
                for final_path in reversed(successful_renames):
                    original = original_contents[final_path]
                    if original is None:
                        if final_path.is_file():
                            final_path.unlink()
                    else:
                        final_path.write_text(original, encoding="utf-8")
                # Clean up all temp files
                for temp_path, final_path in written_temp_paths:
                    if temp_path.is_file():
                        temp_path.unlink()
                raise commit_err

            # Reload index to reflect the written files immediately
            self.reload()

            return SuccessResponse[None](data=None)

        except Exception as e:
            return ErrorResponse(
                error=ContractError.io(
                    path="",
                    message=f"IO error writing profile files: {e}"
                )
            )

    def _get_indexed_profile(self, ref: str) -> Profile | None:
        """Helper to get a Profile from the active index."""
        slug = ref.split("/")[-1]
        kind = ref.split("/")[0] if "/" in ref else ""
        if kind == "people":
            p = self._index._people.get(slug)
            if p:
                return person_to_profile(p, self._index)
        elif kind == "projects":
            pr = self._index._projects.get(slug)
            if pr:
                return project_to_profile(pr, self._index)
        elif kind == "products":
            prod = self._index._products.get(slug)
            if prod:
                return product_to_profile(prod, self._index)
        return None

    def _serialize_profile_to_markdown(self, profile: Profile, slug: str) -> str:
        """Turn a Profile back into the private on-disk markdown+YAML format."""
        # Reconstruct fields dict
        fm = dict(profile.fields)
        fm["type"] = profile.kind

        # Keep/clear relationship lists to prevent duplications
        for rel_name in ["projects", "people", "product"]:
            fm.pop(rel_name, None)

        # Reconstruct relationships in frontmatter
        if profile.kind == "person":
            projects_links = []
            for rel in profile.relationships:
                if rel.name == "projects":
                    t_slug = rel.target.split("/")[-1]
                    display = self._index._titles.get(t_slug, t_slug.replace("-", " ").title())
                    projects_links.append(f"[[{display}]]")
            if projects_links:
                fm["projects"] = projects_links

        elif profile.kind == "project":
            people_links = []
            product_link = None
            for rel in profile.relationships:
                if rel.name == "people":
                    t_slug = rel.target.split("/")[-1]
                    display = self._index._titles.get(t_slug, t_slug.replace("-", " ").title())
                    people_links.append(f"[[{display}]]")
                elif rel.name == "product":
                    t_slug = rel.target.split("/")[-1]
                    display = self._index._titles.get(t_slug, t_slug.replace("-", " ").title())
                    product_link = f"[[{display}]]"
            if people_links:
                fm["people"] = people_links
            if product_link:
                fm["product"] = product_link

        elif profile.kind == "product":
            project_links = []
            for rel in profile.relationships:
                if rel.name == "projects":
                    t_slug = rel.target.split("/")[-1]
                    display = self._index._titles.get(t_slug, t_slug.replace("-", " ").title())
                    project_links.append(f"[[{display}]]")
            if project_links:
                fm["projects"] = project_links

        # Serialize frontmatter
        fm_yaml = yaml.safe_dump(fm, default_flow_style=False, sort_keys=False)

        # Reconstruct body sections
        body_parts = []
        # Find Title heading
        title = fm.get("name") or ""
        if not title:
            # Look for H1 in sections
            for sec in profile.sections:
                if sec.heading and _fold(sec.heading) == _fold(slug.replace("-", " ")):
                    title = sec.heading
                    break
        if not title:
            title = self._index._titles.get(slug, slug.replace("-", " ").title())

        body_parts.append(f"# {title}")

        for sec in profile.sections:
            if sec.heading == title:
                if sec.body:
                    body_parts.append(sec.body)
                continue
            if sec.heading:
                body_parts.append(f"## {sec.heading}")
            if sec.body:
                body_parts.append(sec.body)

        return "---\n" + fm_yaml + "---\n" + "\n".join(body_parts) + "\n"
