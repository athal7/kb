"""Translate engine-internal dataclasses (core/models.py) into Contract Profiles.

The Contract is the only public surface (domain-model/spec.md, Term - Contract): no
consumer should build a `Profile` by reaching into `Person`/`Project` fields itself.
These functions are the single seam that does that translation.

`ref` is currently the vault-relative file path. That satisfies "stable opaque
identifier" for now but not yet "never a file path" (a query-result requirement in
kb-contract/spec.md) — swapping in a true opaque ref is follow-up work once an entity
registry/id scheme lands; today's `Person`/`Project` dataclasses carry no such id.
"""

from __future__ import annotations

from kb.contract.schema_pack import Profile, Relationship, Section
from kb.core.markdown import Section as CoreSection
from kb.core.models import Person, Project, Wikilink


def _translate_section(section: CoreSection) -> Section:
    return Section(heading=section.heading, body=section.body)


def _relationship(name: str, link: Wikilink) -> Relationship:
    return Relationship(name=name, target=link.raw_text)


def person_to_profile(person: Person) -> Profile:
    relationships = [_relationship("projects", link) for link in person.project_links]

    return Profile(
        ref=person.file,
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
        ref=project.file,
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
