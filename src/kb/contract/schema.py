"""JSON Schema generation for the Contract's core typed shapes.

Per kb-contract/spec.md's Contract introspection scenario, `kb contract schema` should
return the Contract's JSON Schema. This module proves JSON Schema generation works
end-to-end for the response envelope and the Profile primitive; wiring it into the CLI
transport is deferred to whenever the click work and this work converge (issue #8's
own scope note — CLI integration is explicitly not required here).
"""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from kb.contract.collector import (
    ActionItem,
    Decision,
    JournalEntry,
    MeetingNote,
    PersonMention,
)
from kb.contract.envelope import ContractResponse
from kb.contract.schema_pack import Profile


def contract_schema() -> dict[str, Any]:
    """Return the JSON Schema for the Contract's response envelope and Profile shape.

    `ContractResponse` is parametrized with `dict` here only to get one concrete
    schema out of the generic; real per-op response types (e.g.
    `ContractResponse[Profile]`) would each generate their own schema the same way.

    `ContractResponse[T]` is a type alias over a discriminated union, not a
    `BaseModel` subclass, so it has no `.model_json_schema()` of its own —
    `TypeAdapter` is pydantic's entry point for getting a schema (or validation) out
    of a bare type rather than a model class.
    """

    return {
        "ContractResponse": TypeAdapter(ContractResponse[dict]).json_schema(),
        "Profile": Profile.model_json_schema(),
        "ActionItem": ActionItem.model_json_schema(),
        "Decision": Decision.model_json_schema(),
        "JournalEntry": JournalEntry.model_json_schema(),
        "MeetingNote": MeetingNote.model_json_schema(),
        "PersonMention": PersonMention.model_json_schema(),
    }
