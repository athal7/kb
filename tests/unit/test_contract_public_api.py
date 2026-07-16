"""kb.contract's __init__ re-exports the package's public surface.

Consumers outside kb.contract should be able to import everything they need from
the package root rather than reaching into submodules directly.
"""


class DescribeContractPublicApi:
    def it_exports_the_envelope_and_error_types(self):
        from kb.contract import CONTRACT_VERSION, ContractError, ContractResponse, ContractWarning

        assert CONTRACT_VERSION
        assert ContractResponse
        assert ContractError
        assert ContractWarning

    def it_exports_the_schema_pack_types(self):
        from kb.contract import (
            Document,
            LedgerEntry,
            Profile,
            Relationship,
            ResolutionMapEntry,
            Section,
        )

        assert Profile and Section and Relationship
        assert ResolutionMapEntry and LedgerEntry and Document

    def it_exports_the_query_types(self):
        from kb.contract import (
            QueryFilter,
            QueryHit,
            QueryRequest,
            QueryResult,
        )

        assert QueryFilter and QueryHit and QueryRequest and QueryResult

    def it_exports_the_translate_functions(self):
        from kb.contract import person_to_profile, product_to_profile, project_to_profile

        assert callable(person_to_profile)
        assert callable(project_to_profile)
        assert callable(product_to_profile)
