"""The Contract boundary layer: typed response envelope, error taxonomy, and schema pack.

Per domain-model/spec.md's Term - Contract requirement, the Contract is the single
typed, versioned JSON interface every Transport speaks — this package is where that
typing lives, translated from the private engine-internal dataclasses in kb.core.
"""

from __future__ import annotations

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
from kb.contract.translate import person_to_profile, project_to_profile
from kb.contract.version import CONTRACT_VERSION

__all__ = [
    "CONTRACT_VERSION",
    "ContractError",
    "ContractResponse",
    "ContractWarning",
    "Document",
    "ErrorResponse",
    "LedgerEntry",
    "Profile",
    "Relationship",
    "ResolutionMapEntry",
    "Section",
    "SuccessResponse",
    "contract_schema",
    "person_to_profile",
    "project_to_profile",
]
