"""ContractResponse models the Contract's response envelope.

Per kb-contract/spec.md's Response Envelope requirement: every response is one JSON
object with contract_version, ok, and either data (success) or error (failure), plus
an always-present warnings array.
"""

import pytest
from pydantic import ValidationError

from kb.contract.envelope import ContractResponse, ContractWarning
from kb.contract.errors import ContractError
from kb.contract.version import CONTRACT_VERSION


class DescribeContractResponse:
    def it_represents_a_successful_response_with_data_and_no_error(self):
        response = ContractResponse[dict](ok=True, data={"name": "Kate"})

        assert response.ok is True
        assert response.data == {"name": "Kate"}
        assert response.error is None
        assert response.warnings == []

    def it_represents_an_error_response_with_error_and_no_data(self):
        error = ContractError(
            code="not_found.person",
            message="no such person",
            path="/id",
            retryable=False,
        )

        response = ContractResponse[dict](ok=False, error=error)

        assert response.ok is False
        assert response.data is None
        assert response.error.code == "not_found.person"
        assert response.error.message == "no such person"
        assert response.error.path == "/id"
        assert response.error.retryable is False

    def it_defaults_contract_version_to_the_current_constant(self):
        response = ContractResponse[dict](ok=True, data={})

        assert response.contract_version == CONTRACT_VERSION

    def it_carries_a_list_of_warnings_that_defaults_to_empty(self):
        warning = ContractWarning(code="deprecation.old_field", message="use new_field instead")

        response = ContractResponse[dict](ok=True, data={}, warnings=[warning])

        assert response.warnings == [warning]
        assert ContractResponse[dict](ok=True, data={}).warnings == []

    def it_rejects_ok_true_with_an_error_set(self):
        error = ContractError(code="io.transient", message="x", path="/x", retryable=True)

        with pytest.raises(ValidationError):
            ContractResponse[dict](ok=True, data={"name": "Kate"}, error=error)

    def it_rejects_ok_false_with_data_set(self):
        error = ContractError(code="io.transient", message="x", path="/x", retryable=True)

        with pytest.raises(ValidationError):
            ContractResponse[dict](ok=False, data={"name": "Kate"}, error=error)
