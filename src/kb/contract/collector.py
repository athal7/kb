"""Pydantic models for generic collector-facing data types (connector contract).

These sit on top of the existing internal data types in `kb.core` as the typed
contract collectors write against when delivering extracted facts/entities.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from kb.contract.schema_pack import Section


class ActionItem(BaseModel):
    """An action item / task extracted by a collector."""

    model_config = ConfigDict(extra="ignore")

    text: str
    checked: bool = False
    person_prefix: str | None = None
    source_group: str | None = None
    wikilinks: list[str] = []
    external_links: list[str] = []
    linear_refs: list[str] = []


class Decision(BaseModel):
    """A decision logged by a collector."""

    model_config = ConfigDict(extra="ignore")

    title: str
    date: str | None = None
    status: str | None = None
    deciders: list[str] = []
    body: str = ""
    sections: list[Section] = []


class JournalEntry(BaseModel):
    """A journal entry logged by a collector."""

    model_config = ConfigDict(extra="ignore")

    date: str
    body: str = ""
    sections: list[Section] = []
    wikilinks: list[str] = []


class MeetingNote(BaseModel):
    """A meeting note logged by a collector."""

    model_config = ConfigDict(extra="ignore")

    title: str
    date: str | None = None
    participants: list[str] = []
    body: str = ""
    sections: list[Section] = []
    wikilinks: list[str] = []


class PersonMention(BaseModel):
    """A person mention/contact captured by a collector."""

    model_config = ConfigDict(extra="ignore")

    name: str
    email: str | None = None
    slack_id: str | None = None
    team: str | None = None
    title: str | None = None
    aliases: list[str] = []
    context: str | None = None
    source: str | None = None
