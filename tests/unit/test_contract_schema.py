"""contract_schema() proves pydantic's .model_json_schema() works end-to-end.

Per kb-contract/spec.md's Contract introspection scenario (`kb contract schema`), the
engine must be able to produce JSON Schema for the Contract's core types. Wiring this
into the CLI is explicitly deferred (issue #8's own scope note); this only proves the
schema is generatable from Python directly.
"""

from kb.contract.schema import contract_schema


class DescribeContractSchema:
    def it_returns_a_discriminated_union_schema_for_the_response_envelope(self):
        schema = contract_schema()

        assert "oneOf" in schema["ContractResponse"]
        assert schema["ContractResponse"]["discriminator"]["propertyName"] == "ok"
        assert schema["Profile"]["type"] == "object"
        assert "properties" in schema["Profile"]

    def it_includes_ref_and_kind_among_profiles_required_properties(self):
        schema = contract_schema()

        assert set(schema["Profile"]["required"]) >= {"ref", "kind"}
