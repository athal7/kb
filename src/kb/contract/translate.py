"""Translate engine-internal dataclasses (core/models.py) into Contract Profiles.

The Contract is the only public surface (domain-model/spec.md, Term - Contract): no
consumer should build a `Profile` by reaching into `Person`/`Project` fields itself.
These functions are the single seam that does that translation.

`ref` is built from the owning collection plus the file's slug (the filename stem,
matching the canonical key `VaultIndex` already derives in `core/index.py`'s
`_canonical_of`) rather than the raw vault-relative path, so it satisfies "never a
file path" (kb-contract/spec.md's Query result-shape requirement). It is not yet the
final stable opaque ref an entity-id scheme would provide (see athal7/kb#3) —
`Person`/`Project` carry no such id today — but it no longer leaks the filesystem
path.

Relationship targets need the same treatment: a `Wikilink.raw_text` is whatever the
author typed (`Firewall`, `[[Firewall]]`, a Slack handle via an alias table, ...), not
a ref — surfacing it verbatim would leak the vault's write-time vocabulary into the
Contract's read-time shape. `_relationship` instead resolves the link through a
`WikilinkResolver` (structurally, `VaultIndex.resolve_wikilink`) to the same
`collection/slug` ref shape `ref` above already produces, falling back to the raw text
only for a resolution the registry genuinely doesn't have an entity for (dead links are
an expected, non-error vault state per `core/models.py`'s `ResolutionStatus`).
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Protocol

from kb.contract.schema_pack import Profile, Relationship, Section
from kb.core.markdown import Section as CoreSection
from kb.core.models import EntityKind, Person, Project, Resolution, ResolutionStatus, Wikilink


class WikilinkResolver(Protocol):
    """Structurally what `VaultIndex.resolve_wikilink` provides — kept as a Protocol
    rather than importing `VaultIndex` directly so this module doesn't have to depend
    on the whole vault-scanning machinery to describe what it needs from it.
    """

    def resolve_wikilink(self, target: str, kind: EntityKind) -> Resolution: ...


def _translate_section(section: CoreSection) -> Section:
    return Section(heading=section.heading, body=section.body)


def _ref_from_file(file: str) -> str:
    """Vault-relative file path with its extension stripped, e.g.
    `projects/firewall.md` -> `projects/firewall`.
    """
    return PurePosixPath(file).with_suffix("").as_posix()


def _relationship(
    name: str, link: Wikilink, kind: EntityKind, resolver: WikilinkResolver
) -> Relationship:
    resolution = resolver.resolve_wikilink(link.raw_text, kind)
    if resolution.status is ResolutionStatus.RESOLVED and resolution.entity.file is not None:
        target = _ref_from_file(resolution.entity.file)
    else:
        target = link.raw_text
    return Relationship(name=name, target=target)


def _slug(file: str) -> str:
    """The filename stem, e.g. `people/ksilverstein.md` -> `ksilverstein`."""
    return PurePosixPath(file).stem


def person_to_profile(person: Person, resolver: WikilinkResolver) -> Profile:
    relationships = [
        _relationship("projects", link, EntityKind.PROJECT, resolver)
        for link in person.project_links
    ]

    return Profile(
        ref=f"people/{_slug(person.file)}",
        kind="person",
        fields={
            "email": person.email,
            "team": person.team,
            "title": person.title,
            "slack_id": person.slack_id,
            "aliases": person.aliases,
        },
        sections=[_translate_section(s) for s in person.sections],
        relationships=relationships,
    )


def project_to_profile(project: Project, resolver: WikilinkResolver) -> Profile:
    relationships = []
    if project.product_link is not None:
        relationships.append(
            _relationship("product", project.product_link, EntityKind.PRODUCT, resolver)
        )
    relationships.extend(
        _relationship("people", link, EntityKind.PERSON, resolver)
        for link in project.people_links
    )

    return Profile(
        ref=f"projects/{_slug(project.file)}",
        kind="project",
        fields={
            "status": project.status,
            "github": project.github,
            "linear": project.linear,
            "aliases": project.aliases,
        },
        sections=[_translate_section(s) for s in project.sections],
        relationships=relationships,
    )
