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

from kb.contract.envelope import ContractResponse
from kb.contract.schema_pack import Profile


def contract_schema() -> dict[str, Any]:
    """
    Generate JSON Schema definitions for the Contract response envelope and `Profile` shape.
    
    Returns:
        dict[str, Any]: A mapping containing the `ContractResponse` and `Profile` JSON Schemas.
    """

    return {
        "ContractResponse": TypeAdapter(ContractResponse[dict]).json_schema(),
        "Profile": Profile.model_json_schema(),
    }
