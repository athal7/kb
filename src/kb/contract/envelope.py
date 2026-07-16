"""The Contract's response envelope.

Per kb-contract/spec.md's Response Envelope requirement: every Contract response is
one JSON object with `contract_version`, `ok`, and either `data` (on success) or
`error` (on failure), plus an always-present `warnings` array (empty when there are
none).

`ContractResponse` is generic over its `data` payload (PEP 695 type parameter syntax,
`class ContractResponse[T]`) rather than typed `Any`, so each Engine op can declare
its own response type (e.g. `ContractResponse[Profile]`) and get real type-checking on
`.data` at call sites, instead of every caller re-casting an `Any`. The cost is that
callers must parametrize the generic explicitly (`ContractResponse[Profile]`, not bare
`ContractResponse`) — an acceptable tradeoff since every real endpoint has one
concrete payload shape. Pydantic has full runtime support for PEP 695 generics since
v2.11 (this project pins pydantic>=2.0 but resolves to 2.13+); the old
`Generic[T]`-subclass spelling is equivalent at runtime but PEP 695 is what ruff's
UP046 expects on a py312-targeted codebase.
"""

from __future__ import annotations

from pydantic import BaseModel, model_validator

from kb.contract.errors import ContractError
from kb.contract.version import CONTRACT_VERSION


class ContractWarning(BaseModel):
    """A non-fatal, namespaced notice attached to a response.

    Named `ContractWarning` rather than `Warning` to avoid shadowing the Python
    builtin exception of the same name. Per the spec's Deprecation window scenario,
    `code` is namespaced (e.g. `deprecation.old_field`).
    """

    code: str
    message: str = ""


class ContractResponse[T](BaseModel):
    contract_version: str = CONTRACT_VERSION
    ok: bool
    data: T | None = None
    error: ContractError | None = None
    warnings: list[ContractWarning] = []

    @model_validator(mode="after")
    def _enforce_ok_data_error_invariant(self) -> ContractResponse[T]:
        if self.ok:
            if self.data is None:
                raise ValueError("ok=True responses must include data")
            if self.error is not None:
                raise ValueError("ok=True responses must not include error")
        else:
            if self.error is None:
                raise ValueError("ok=False responses must include error")
            if self.data is not None:
                raise ValueError("ok=False responses must not include data")
        return self
