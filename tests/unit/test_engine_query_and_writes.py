"""Unit and integration tests for the KB Engine's query and write operations.

These tests assert contract conformance, write invariants (section caps, relationship symmetry,
alias sync), and query capabilities using the anonymized fixtures.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from kb.contract.query import QueryFilter, QueryRequest
from kb.contract.schema_pack import Profile, Relationship, Section
from kb.core.engine import Engine

VAULT = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.fixture
def temp_vault(tmp_path) -> Path:
    """Create a temporary copy of the anonymized fixture KB for safe write testing."""
    shutil.copytree(VAULT, tmp_path, dirs_exist_ok=True)
    return tmp_path


class DescribeEngineQuery:
    def it_performs_substring_search_across_sections_and_fields(self):
        engine = Engine(VAULT)

        # Searching for "gRPC" which is in Andrew Thal's section body
        req = QueryRequest(text="gRPC")
        resp = engine.query(req)

        assert resp.ok is True
        assert len(resp.data.hits) > 0
        hit = resp.data.hits[0]
        assert hit.ref == "people/andrew-thal"
        assert hit.collection == "people"
        assert "gRPC" in hit.snippet
        assert hit.matched_in.startswith("sections")

    def it_supports_field_level_filters(self):
        engine = Engine(VAULT)

        # Filter for status = active in projects
        req = QueryRequest(
            collections=["projects"],
            filters=[QueryFilter(field="status", op="=", value="active")]
        )
        resp = engine.query(req)

        assert resp.ok is True
        assert len(resp.data.hits) > 0
        assert any(hit.ref == "projects/firewall" for hit in resp.data.hits)
        for hit in resp.data.hits:
            assert hit.collection == "projects"
            # Get the profile to assert the field
            p = engine._get_indexed_profile(hit.ref)
            assert p.fields["status"] == "active"

    def it_supports_collection_scoping(self):
        engine = Engine(VAULT)

        # Scope to 'journal' only
        req = QueryRequest(collections=["journal"])
        resp = engine.query(req)

        assert resp.ok is True
        assert len(resp.data.hits) > 0
        assert any(hit.ref.startswith("journal/") for hit in resp.data.hits)
        for hit in resp.data.hits:
            assert hit.collection == "journal"

    def it_supports_relationship_traversal_outgoing(self):
        engine = Engine(VAULT)

        # Traversal: projects related to "people/andrew-thal"
        req = QueryRequest(
            related_to="people/andrew-thal",
            relationship="projects"
        )
        resp = engine.query(req)

        assert resp.ok is True
        assert len(resp.data.hits) > 0
        refs = [h.ref for h in resp.data.hits]
        assert "projects/firewall" in refs

    def it_supports_relationship_traversal_incoming(self):
        engine = Engine(VAULT)

        # Traversal: people on project "projects/firewall"
        req = QueryRequest(
            related_to="projects/firewall",
            relationship="people"
        )
        resp = engine.query(req)

        assert resp.ok is True
        assert len(resp.data.hits) > 0
        refs = [h.ref for h in resp.data.hits]
        assert "people/stephen-golub" in refs or "people/andrew-thal" in refs

    def it_resolves_alias_aware_query_terms(self):
        engine = Engine(VAULT)

        # "athal" is an alias of "Andrew Thal"
        req = QueryRequest(text="athal", collections=["people"])
        resp = engine.query(req)

        assert resp.ok is True
        assert len(resp.data.hits) > 0
        refs = [h.ref for h in resp.data.hits]
        assert "people/andrew-thal" in refs


class DescribeEngineWrites:
    def it_enforces_section_caps_on_current_section(self, temp_vault):
        engine = Engine(temp_vault)

        # Construct a profile with more than 5 bullets in 'Current' section
        too_many_bullets = "\n".join([f"- Item {i}" for i in range(1, 7)])
        bad_profile = Profile(
            ref="people/bad-test",
            kind="person",
            fields={"email": "bad@example.com"},
            sections=[
                Section(heading="Current", body=too_many_bullets)
            ]
        )

        resp = engine.write_profile(bad_profile)

        assert resp.ok is False
        assert resp.error.code == "validation.section_cap"
        assert resp.error.path == "/sections"

        # Verify that file was NOT created on disk
        assert not (temp_vault / "people" / "bad-test.md").is_file()

    def it_syncs_bidirectional_relationships_upon_write(self, temp_vault):
        engine = Engine(temp_vault)

        # Andre (people/andre) has no relationship to projects/webservices initially
        # Let's save Andre with a relationship pointing to projects/webservices
        andre = engine._get_indexed_profile("people/andre")
        assert andre is not None
        assert len(andre.relationships) == 0

        # Add projects relationship pointing to projects/webservices
        andre.relationships.append(
            Relationship(name="projects", target="projects/webservices")
        )

        resp = engine.write_profile(andre)
        assert resp.ok is True

        # Reload target and verify that projects/webservices got the inverse
        # 'people' relationship back to Andre
        webservices = engine._get_indexed_profile("projects/webservices")
        assert webservices is not None
        has_inverse = any(
            r.name == "people" and r.target == "people/andre"
            for r in webservices.relationships
        )
        assert has_inverse is True

    def it_syncs_aliases_to_the_resolution_map(self, temp_vault):
        engine = Engine(temp_vault)

        # Save a person with new aliases
        kate = engine._get_indexed_profile("people/ksilverstein")
        assert kate is not None

        kate.fields["aliases"] = ["Katie", "ksilv"]
        resp = engine.write_profile(kate)
        assert resp.ok is True

        # Read names.json and assert the aliases exist
        names_json = json.loads((temp_vault / "names.json").read_text(encoding="utf-8"))
        assert names_json["Katie"] == "Kate Silverstein"
        assert names_json["ksilv"] == "Kate Silverstein"
        # Old aliases not in the list should be cleaned up
        assert "kate" not in names_json

    def it_generates_slug_if_not_specified(self, temp_vault):
        engine = Engine(temp_vault)

        new_profile = Profile(
            ref="",
            kind="person",
            fields={"name": "George Washington", "email": "george@example.com"}
        )

        resp = engine.write_profile(new_profile)
        assert resp.ok is True

        # Generated ref should be people/george-washington
        assert new_profile.ref == "people/george-washington"
        assert (temp_vault / "people" / "george-washington.md").is_file()
