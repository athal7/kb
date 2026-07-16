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
"""

from __future__ import annotations

from pathlib import PurePosixPath

from kb.contract.schema_pack import Profile, Relationship, Section
from kb.core.markdown import Section as CoreSection
from kb.core.models import Person, Project, Wikilink


def _translate_section(section: CoreSection) -> Section:
    return Section(heading=section.heading, body=section.body)


def _relationship(name: str, link: Wikilink) -> Relationship:
    return Relationship(name=name, target=link.raw_text)


def _slug(file: str) -> str:
    """The filename stem, e.g. `people/ksilverstein.md` -> `ksilverstein`."""
    return PurePosixPath(file).stem


def person_to_profile(person: Person) -> Profile:
    relationships = [_relationship("projects", link) for link in person.project_links]

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


def project_to_profile(project: Project) -> Profile:
    relationships = []
    if project.product_link is not None:
        relationships.append(_relationship("product", project.product_link))
    relationships.extend(_relationship("people", link) for link in project.people_links)

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
