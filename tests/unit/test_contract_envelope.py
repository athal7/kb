"""SuccessResponse/ErrorResponse model the Contract's response envelope.

Per kb-contract/spec.md's Response Envelope requirement: every response is one JSON
object with contract_version, ok, and either data (success) or error (failure), plus
an always-present warnings array. The two outcomes are modeled as separate variants of
a discriminated union (`ContractResponse`) rather than one model with both fields
optional, so the ok/data/error invariant is visible in the JSON Schema itself, not
just enforced at runtime.
"""

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from kb.contract.envelope import ContractResponse, ContractWarning, ErrorResponse, SuccessResponse
from kb.contract.errors import ContractError
from kb.contract.version import CONTRACT_VERSION


class DescribeSuccessResponse:
    def it_represents_a_successful_response_with_data_and_no_error_field(self):
        response = SuccessResponse[dict](data={"name": "Kate"})

        assert response.ok is True
        assert response.data == {"name": "Kate"}
        assert not hasattr(response, "error")

    def it_defaults_contract_version_to_the_current_constant(self):
        response = SuccessResponse[dict](data={})

        assert response.contract_version == CONTRACT_VERSION

    def it_carries_a_list_of_warnings_that_defaults_to_empty(self):
        warning = ContractWarning(code="deprecation.old_field", message="use new_field instead")

        response = SuccessResponse[dict](data={}, warnings=[warning])

        assert response.warnings == [warning]
        assert SuccessResponse[dict](data={}).warnings == []

    def it_rejects_construction_without_data(self):
        with pytest.raises(ValidationError):
            SuccessResponse[dict]()

    def it_rejects_an_error_field_since_none_exists_on_this_variant(self):
        error = ContractError(code="io.transient", message="x", path="/x", retryable=True)

        with pytest.raises(ValidationError):
            SuccessResponse[dict](data={"name": "Kate"}, error=error)


class DescribeErrorResponse:
    def it_represents_an_error_response_with_error_and_no_data_field(self):
        error = ContractError(
            code="not_found.person",
            message="no such person",
            path="/id",
            retryable=False,
        )

        response = ErrorResponse(error=error)

        assert response.ok is False
        assert not hasattr(response, "data")
        assert response.error.code == "not_found.person"
        assert response.error.message == "no such person"
        assert response.error.path == "/id"
        assert response.error.retryable is False

    def it_rejects_construction_without_error(self):
        with pytest.raises(ValidationError):
            ErrorResponse()

    def it_rejects_a_data_field_since_none_exists_on_this_variant(self):
        error = ContractError(code="io.transient", message="x", path="/x", retryable=True)

        with pytest.raises(ValidationError):
            ErrorResponse(error=error, data={"name": "Kate"})


class DescribeContractResponseSchema:
    """`ContractResponse[T]` is a discriminated union, not a single flat model — its
    generated JSON Schema should show that structurally (`oneOf` + a discriminator
    keyed on `ok`), not just enforce it at runtime.
    """

    class _Payload(BaseModel):
        name: str

    def it_generates_a_schema_with_a_oneof_of_the_two_variants(self):
        schema = TypeAdapter(ContractResponse[self._Payload]).json_schema()

        assert "oneOf" in schema
        assert len(schema["oneOf"]) == 2

    def it_generates_a_schema_with_a_discriminator_keyed_on_ok(self):
        schema = TypeAdapter(ContractResponse[self._Payload]).json_schema()

        assert schema["discriminator"]["propertyName"] == "ok"
        assert len(schema["discriminator"]["mapping"]) == 2

    def it_marks_data_as_required_only_in_the_success_variant_schema(self):
        schema = TypeAdapter(ContractResponse[self._Payload]).json_schema()

        variants = schema["$defs"]
        success = next(v for k, v in variants.items() if k.startswith("SuccessResponse"))
        error = variants["ErrorResponse"]

        assert "data" in success["properties"]
        assert "error" not in success["properties"]
        assert "error" in error["properties"]
        assert "data" not in error["properties"]
