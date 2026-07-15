"""The Contract's error taxonomy.

Per kb-contract/spec.md's Error Codes requirement, every error carries a stable,
namespaced `code` from a fixed set of prefixes, a human `message`, a `path` field
(JSON Pointer format, e.g. `/frontmatter/status` — a plain string; this module does
not validate full JSON Pointer syntax, only the code's namespace prefix), and a
`retryable` flag distinguishing transient failures (io.*) from deterministic ones.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

ALLOWED_CODE_PREFIXES = ("validation.", "not_found.", "conflict.", "contract.", "io.")


class ContractError(BaseModel):
    code: str
    message: str
    path: str
    retryable: bool

    @field_validator("code")
    @classmethod
    def _code_must_use_an_allowed_prefix(cls, value: str) -> str:
        if not value.startswith(ALLOWED_CODE_PREFIXES):
            raise ValueError(
                f"code {value!r} must start with one of {ALLOWED_CODE_PREFIXES}"
            )
        return value

    @classmethod
    def not_found(
        cls, *, path: str, message: str, code: str = "not_found.entity"
    ) -> ContractError:
        return cls(code=code, message=message, path=path, retryable=False)

    @classmethod
    def validation(
        cls, *, path: str, message: str, code: str = "validation.invariant"
    ) -> ContractError:
        return cls(code=code, message=message, path=path, retryable=False)

    @classmethod
    def conflict(
        cls, *, path: str, message: str, code: str = "conflict.duplicate"
    ) -> ContractError:
        return cls(code=code, message=message, path=path, retryable=False)

    @classmethod
    def contract(
        cls, *, path: str, message: str, code: str = "contract.unsupported_version"
    ) -> ContractError:
        return cls(code=code, message=message, path=path, retryable=False)

    @classmethod
    def io(cls, *, path: str, message: str, code: str = "io.transient") -> ContractError:
        return cls(code=code, message=message, path=path, retryable=True)
