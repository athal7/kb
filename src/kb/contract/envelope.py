"""The Contract's response envelope.

Per kb-contract/spec.md's Response Envelope requirement: every Contract response is
one JSON object with `contract_version`, `ok`, and either `data` (on success) or
`error` (on failure), plus an always-present `warnings` array (empty when there are
none).

A single flat model with `ok: bool` and both `data`/`error` typed `X | None` can only
enforce "ok=True implies data present, error absent" with a runtime `model_validator`
— its `.model_json_schema()` still describes `data`/`error` as two independently
optional fields with no relationship between them, so a schema consumer (e.g. a future
`kb contract schema`) can't see the constraint at all. Modeling the two outcomes as
separate variants — `SuccessResponse[T]` (`ok: Literal[True]`, required `data`, no
`error` field) and `ErrorResponse` (`ok: Literal[False]`, required `error`, no `data`
field) — joined by a `Field(discriminator="ok")` union makes the invariant part of the
type itself: there is no longer an invalid combination of fields to reject, so no
`model_validator` is needed, and pydantic renders the union as a JSON Schema `oneOf`
with a discriminator mapping keyed by `ok`.

`SuccessResponse` is generic over its `data` payload (PEP 695 type parameter syntax,
`class SuccessResponse[T]`) rather than typed `Any`, so each Engine op can declare its
own response type (e.g. `ContractResponse[Profile]`) and get real type-checking on
`.data` at call sites, instead of every caller re-casting an `Any`. `ContractResponse`
itself is a PEP 695 generic type alias over the discriminated union, not a class — call
sites construct `SuccessResponse[Profile](data=...)` or `ErrorResponse(error=...)`
directly and use `ContractResponse[Profile]` only as the annotation/schema type.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

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


class _ContractResponseBase(BaseModel):
    """Fields every Contract response carries regardless of success or failure.

    `extra="forbid"` matters here specifically: without it, a caller building
    `SuccessResponse(data=..., error=...)` would have the stray `error` kwarg silently
    dropped rather than rejected, which would quietly defeat the point of splitting
    the envelope into variants in the first place.
    """

    model_config = ConfigDict(extra="forbid")

    contract_version: str = CONTRACT_VERSION
    warnings: list[ContractWarning] = []


class SuccessResponse[T](_ContractResponseBase):
    ok: Literal[True] = True
    data: T


class ErrorResponse(_ContractResponseBase):
    ok: Literal[False] = False
    error: ContractError


type ContractResponse[T] = Annotated[
    SuccessResponse[T] | ErrorResponse, Field(discriminator="ok")
]
