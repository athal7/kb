"""The Contract boundary layer: typed response envelope, error taxonomy, and schema pack.

Per domain-model/spec.md's Term - Contract requirement, the Contract is the single
typed, versioned JSON interface every Transport speaks — this package is where that
typing lives, translated from the private engine-internal dataclasses in kb.core.
"""

from __future__ import annotations

from kb.contract.collector import (
    ActionItem,
    Decision,
    JournalEntry,
    MeetingNote,
    PersonMention,
)
from kb.contract.envelope import ContractResponse, ContractWarning, ErrorResponse, SuccessResponse
from kb.contract.errors import ContractError
from kb.contract.schema import contract_schema
from kb.contract.schema_pack import (
    Document,
    LedgerEntry,
    Profile,
    Relationship,
    ResolutionMapEntry,
    Section,
)
from kb.contract.translate import (
    action_item_to_core,
    decision_from_core,
    decision_to_core,
    journal_entry_from_core,
    journal_entry_to_core,
    meeting_note_from_core,
    meeting_note_to_core,
    person_mention_from_core,
    person_mention_to_core,
    person_to_profile,
    project_to_profile,
)
from kb.contract.version import CONTRACT_VERSION

__all__ = [
    "ActionItem",
    "CONTRACT_VERSION",
    "ContractError",
    "ContractResponse",
    "ContractWarning",
    "Decision",
    "Document",
    "ErrorResponse",
    "JournalEntry",
    "LedgerEntry",
    "MeetingNote",
    "PersonMention",
    "Profile",
    "Relationship",
    "ResolutionMapEntry",
    "Section",
    "SuccessResponse",
    "action_item_to_core",
    "contract_schema",
    "decision_from_core",
    "decision_to_core",
    "journal_entry_from_core",
    "journal_entry_to_core",
    "meeting_note_from_core",
    "meeting_note_to_core",
    "person_mention_from_core",
    "person_mention_to_core",
    "person_to_profile",
    "project_to_profile",
]
