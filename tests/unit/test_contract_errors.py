"""ContractError models the Contract's namespaced error taxonomy.

Per kb-contract/spec.md's Error Codes requirement, every error carries a code from a
fixed enum of prefixes (validation.*, not_found.*, conflict.*, contract.*, io.*), a
message, a JSON-Pointer-shaped path into the offending field, and a retryable flag.
"""

import pytest
from pydantic import ValidationError

from kb.contract.errors import ContractError


class DescribeContractError:
    def it_accepts_a_code_from_each_allowed_prefix(self):
        for code in [
            "validation.section_cap_exceeded",
            "not_found.person",
            "conflict.duplicate_alias",
            "contract.unsupported_version",
            "io.lock_contention",
        ]:
            error = ContractError(code=code, message="x", path="/x", retryable=False)
            assert error.code == code

    def it_rejects_a_code_outside_the_allowed_prefixes(self):
        with pytest.raises(ValidationError):
            ContractError(code="totally_unknown.thing", message="x", path="/x", retryable=False)

    def it_carries_a_json_pointer_path_and_retryable_flag(self):
        error = ContractError(
            code="io.disk_error",
            message="disk full",
            path="/data/body",
            retryable=True,
        )

        assert error.path == "/data/body"
        assert error.retryable is True


class DescribeContractErrorFactories:
    def it_builds_a_not_found_error_with_sensible_defaults(self):
        error = ContractError.not_found(path="/id", message="no such person")

        assert error.code == "not_found.entity"
        assert error.retryable is False
        assert error.path == "/id"
        assert error.message == "no such person"

    def it_builds_a_validation_error_with_sensible_defaults(self):
        error = ContractError.validation(path="/sections/6", message="too many sections")

        assert error.code == "validation.invariant"
        assert error.retryable is False

    def it_builds_a_conflict_error_with_sensible_defaults(self):
        error = ContractError.conflict(path="/aliases/1", message="alias already claimed")

        assert error.code == "conflict.duplicate"
        assert error.retryable is False
        assert error.path == "/aliases/1"
        assert error.message == "alias already claimed"

    def it_builds_a_contract_error_with_sensible_defaults(self):
        error = ContractError.contract(path="/contract_version", message="unsupported version")

        assert error.code == "contract.unsupported_version"
        assert error.retryable is False
        assert error.path == "/contract_version"
        assert error.message == "unsupported version"

    def it_builds_an_io_error_that_is_retryable_by_default(self):
        error = ContractError.io(path="/store", message="lock contention")

        assert error.code == "io.transient"
        assert error.retryable is True
