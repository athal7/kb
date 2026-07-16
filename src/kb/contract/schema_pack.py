"""Typed shapes for the schema pack's four generic primitives.

Per domain-model/spec.md: a Profile is typed fields + ordered freeform dated Sections
+ typed Relationships to other Profiles; a Resolution map entry is a variant ->
canonical lookup with a suppress sentinel; a Ledger entry is an identity key + JSON
payload + latest-wins timestamp; a Document is a namespaced long-form record with an
optional provenance sidecar.

These models capture the SHAPE the spec describes generically. They do not yet
losslessly round-trip every real field of `Person`/`Project`/`Product` (see
`kb.contract.translate` for the current translation coverage) — that per-collection
field migration is deliberately out of scope for this pass; the goal here is the
typed Contract scaffolding and JSON Schema generation working end-to-end.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, model_validator


class Section(BaseModel):
    """One ordered, optionally-dated slice of a Profile's freeform body."""

    heading: str | None = None
    date: str | None = None
    body: str = ""


class Relationship(BaseModel):
    """A typed, named edge from a Profile to another Profile via an opaque ref."""

    name: str
    target: str


class Profile(BaseModel):
    """A structured record: typed fields + ordered dated Sections + Relationships.

    `ref` is the stable opaque identifier for this record (never a file path, per the
    Contract's Query result-shape requirement). `kind` names the owning collection
    (e.g. "person", "project"). `fields` holds the collection's typed frontmatter-style
    fields; a fully data-driven schema pack would type these per-collection, which is
    future work — for now this is an open dict, documented as such.
    """

    ref: str
    kind: str
    fields: dict[str, Any] = {}
    sections: list[Section] = []
    relationships: list[Relationship] = []


class ResolutionMapEntry(BaseModel):
    """One variant -> canonical row in a Resolution map.

    `suppressed` is derived from the empty-canonical sentinel rather than stored
    independently, so it can never drift out of sync with `canonical`.
    """

    variant: str
    canonical: str
    suppressed: bool = False

    @model_validator(mode="after")
    def _derive_suppressed_from_empty_canonical(self) -> ResolutionMapEntry:
        self.suppressed = self.canonical == ""
        return self


class LedgerEntry(BaseModel):
    """One append-only Ledger row; the latest entry per `key` is the current state."""

    key: str
    payload: dict[str, Any]
    timestamp: datetime


class Document(BaseModel):
    """A namespaced long-form Document store record with optional provenance."""

    namespace: str
    kind: str
    body: str
    provenance: dict[str, Any] | None = None
