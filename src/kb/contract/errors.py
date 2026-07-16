"""The Contract's error taxonomy.

Per kb-contract/spec.md's Error Codes requirement, every error carries a stable,
namespaced `code` from a fixed set of prefixes, a human `message`, a `path` field
(RFC 6901 JSON Pointer, e.g. `/frontmatter/status` or `` for the document root), and a
`retryable` flag distinguishing transient failures (io.*) from deterministic ones.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, field_validator

ALLOWED_CODE_PREFIXES = ("validation.", "not_found.", "conflict.", "contract.", "io.")

# RFC 6901 §3: a pointer is either empty (whole document) or a sequence of `/`-prefixed
# segments; within a segment, `~` is only valid as `~0` (-> `~`) or `~1` (-> `/`) — any
# other character after `~` is a malformed escape.
_INVALID_TILDE_ESCAPE = re.compile(r"~(?![01])")


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

    @field_validator("path")
    @classmethod
    def _path_must_be_a_valid_json_pointer(cls, value: str) -> str:
        if value == "":
            return value
        if not value.startswith("/"):
            raise ValueError(f"path {value!r} must be '' or start with '/' (RFC 6901)")
        if _INVALID_TILDE_ESCAPE.search(value):
            raise ValueError(
                f"path {value!r} has a '~' not followed by '0' or '1' (RFC 6901 escape)"
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
