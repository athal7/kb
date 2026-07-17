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

from kb.contract.collector import (
    ActionItem as CollectorActionItem,
    Decision as CollectorDecision,
    JournalEntry as CollectorJournalEntry,
    MeetingNote as CollectorMeetingNote,
    PersonMention as CollectorPersonMention,
)
from kb.contract.schema_pack import Profile, Relationship, Section
from kb.core.actionitems import ActionItem as CoreActionItem
from kb.core.markdown import Section as CoreSection
from kb.core.models import (
    Decision as CoreDecision,
    EntityKind,
    JournalEntry as CoreJournalEntry,
    Person,
    Person as CorePerson,
    Project,
    Resolution,
    ResolutionStatus,
    Wikilink,
    Wikilink as CoreWikilink,
)


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


def section_to_core(section: Section, default_level: int = 2) -> CoreSection:
    """Convert a Contract Section to a Core Section."""
    lines = section.body.split("\n") if section.body else []
    level = default_level if section.heading else 0
    return CoreSection(heading=section.heading, level=level, lines=lines)


def action_item_to_core(item: CollectorActionItem) -> CoreActionItem:
    """Convert a collector ActionItem to a core ActionItem."""
    person = f"**{item.person_prefix}**: " if item.person_prefix else ""
    marker = "[x]" if item.checked else "[ ]"
    raw_line = f"- {marker} {person}{item.text}"
    return CoreActionItem(
        source_group=item.source_group,
        checked=item.checked,
        text=item.text,
        raw_line=raw_line,
        line_no=-1,
        person_prefix=item.person_prefix,
        wikilinks=item.wikilinks,
        external_links=item.external_links,
        linear_refs=item.linear_refs,
    )


def decision_to_core(decision: CollectorDecision, file_path: str = "") -> CoreDecision:
    """Convert a collector Decision to a core Decision."""
    core_sections = []
    if decision.body:
        core_sections.append(CoreSection(heading=None, level=0, lines=decision.body.split("\n")))
    for sec in decision.sections:
        core_sections.append(section_to_core(sec))
    return CoreDecision(
        file=file_path,
        is_readonly=False,
        sections=core_sections,
    )


def decision_from_core(core: CoreDecision) -> CollectorDecision:
    """Convert a core Decision to a collector Decision."""
    sections = []
    body_parts = []
    for sec in core.sections:
        if sec.heading is None:
            body_parts.append(sec.body)
        else:
            sections.append(_translate_section(sec))
    return CollectorDecision(
        title=PurePosixPath(core.file).stem if core.file else "",
        body="\n\n".join(body_parts),
        sections=sections,
    )


def journal_entry_to_core(entry: CollectorJournalEntry, file_path: str = "") -> CoreJournalEntry:
    """Convert a collector JournalEntry to a core JournalEntry."""
    core_sections = []
    if entry.body:
        core_sections.append(CoreSection(heading=None, level=0, lines=entry.body.split("\n")))
    for sec in entry.sections:
        core_sections.append(section_to_core(sec))

    wikilinks = [
        CoreWikilink(raw_text=link, source_file=file_path, source_line=-1)
        for link in entry.wikilinks
    ]
    return CoreJournalEntry(
        file=file_path,
        date=entry.date,
        sections=core_sections,
        wikilinks=wikilinks,
    )


def journal_entry_from_core(core: CoreJournalEntry) -> CollectorJournalEntry:
    """Convert a core JournalEntry to a collector JournalEntry."""
    sections = []
    body_parts = []
    for sec in core.sections:
        if sec.heading is None:
            body_parts.append(sec.body)
        else:
            sections.append(_translate_section(sec))
    wikilinks = [link.raw_text for link in core.wikilinks]
    return CollectorJournalEntry(
        date=core.date,
        body="\n\n".join(body_parts),
        sections=sections,
        wikilinks=wikilinks,
    )


def meeting_note_to_core(note: CollectorMeetingNote, file_path: str = "") -> CoreJournalEntry:
    """Convert a collector MeetingNote to a core JournalEntry."""
    core_sections = []
    if note.body:
        core_sections.append(CoreSection(heading=None, level=0, lines=note.body.split("\n")))
    for sec in note.sections:
        core_sections.append(section_to_core(sec))

    wikilinks = [
        CoreWikilink(raw_text=link, source_file=file_path, source_line=-1)
        for link in note.wikilinks
    ]
    return CoreJournalEntry(
        file=file_path,
        date=note.date or "",
        sections=core_sections,
        wikilinks=wikilinks,
    )


def person_mention_to_core(mention: CollectorPersonMention, file_path: str = "") -> CorePerson:
    """Convert a collector PersonMention to a core Person."""
    frontmatter = {
        "email": mention.email,
        "team": mention.team,
        "title": mention.title,
        "slack_id": mention.slack_id,
        "aliases": mention.aliases,
    }
    frontmatter = {k: v for k, v in frontmatter.items() if v is not None}

    core_sections = []
    if mention.context:
        core_sections.append(
            CoreSection(heading="Context", level=2, lines=[mention.context])
        )

    return CorePerson(
        file=file_path,
        frontmatter=frontmatter,
        email=mention.email,
        team=mention.team,
        title=mention.title,
        slack_id=mention.slack_id,
        aliases=mention.aliases,
        project_links=[],
        sections=core_sections,
    )


def person_mention_from_core(core: CorePerson) -> CollectorPersonMention:
    """Convert a core Person to a collector PersonMention."""
    context_sec = core.section("Context")
    context = context_sec.body if context_sec else None
    return CollectorPersonMention(
        name=PurePosixPath(core.file).stem if core.file else "",
        email=core.email,
        slack_id=core.slack_id,
        team=core.team,
        title=core.title,
        aliases=core.aliases,
        context=context,
    )
