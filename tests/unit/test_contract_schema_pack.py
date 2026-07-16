"""Typed shapes for the four schema-pack primitives from domain-model/spec.md.

Profile: typed fields + ordered dated Sections + typed Relationships.
Resolution map entry: variant -> canonical, with the empty-canonical suppress sentinel.
Ledger entry: identity key + JSON payload + timestamp.
Document: namespace + kind + body + optional provenance sidecar.
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from kb.contract.schema_pack import (
    Document,
    LedgerEntry,
    Profile,
    Relationship,
    ResolutionMapEntry,
    Section,
)


class DescribeSection:
    def it_holds_a_heading_optional_date_and_body(self):
        section = Section(heading="Current", date="2026-07-10", body="- doing the thing")

        assert section.heading == "Current"
        assert section.date == "2026-07-10"
        assert section.body == "- doing the thing"

    def it_allows_a_missing_heading_and_date_for_leading_preamble(self):
        section = Section(body="preamble text")

        assert section.heading is None
        assert section.date is None


class DescribeRelationship:
    def it_holds_a_name_and_a_target_ref(self):
        relationship = Relationship(name="projects", target="ref:project:firewall")

        assert relationship.name == "projects"
        assert relationship.target == "ref:project:firewall"

    def it_rejects_a_relationship_missing_a_target(self):
        with pytest.raises(ValidationError):
            Relationship(name="projects")


class DescribeProfile:
    def it_constructs_from_ref_kind_fields_sections_and_relationships(self):
        profile = Profile(
            ref="ref:person:ksilverstein",
            kind="person",
            fields={"email": "k@example.com", "team": "Research"},
            sections=[Section(heading="Current", body="ML researcher")],
            relationships=[Relationship(name="projects", target="ref:project:firewall")],
        )

        assert profile.ref == "ref:person:ksilverstein"
        assert profile.kind == "person"
        assert profile.fields["team"] == "Research"
        assert profile.sections[0].heading == "Current"
        assert profile.relationships[0].target == "ref:project:firewall"

    def it_defaults_sections_and_relationships_to_empty(self):
        profile = Profile(ref="ref:person:x", kind="person", fields={})

        assert profile.sections == []
        assert profile.relationships == []

    def it_rejects_a_profile_missing_a_ref(self):
        with pytest.raises(ValidationError):
            Profile(kind="person", fields={})


class DescribeResolutionMapEntry:
    def it_reports_not_suppressed_when_canonical_is_present(self):
        entry = ResolutionMapEntry(variant="Kate", canonical="Kate Silverstein")

        assert entry.canonical == "Kate Silverstein"
        assert entry.suppressed is False

    def it_derives_suppressed_from_an_empty_canonical(self):
        entry = ResolutionMapEntry(variant="noise-term", canonical="")

        assert entry.suppressed is True


class DescribeLedgerEntry:
    def it_holds_an_identity_key_json_payload_and_timestamp(self):
        entry = LedgerEntry(
            key="action-item:123",
            payload={"text": "follow up", "done": False},
            timestamp=datetime(2026, 7, 10, 9, 0, 0),
        )

        assert entry.key == "action-item:123"
        assert entry.payload["text"] == "follow up"
        assert entry.timestamp == datetime(2026, 7, 10, 9, 0, 0)

    def it_rejects_an_entry_missing_a_key(self):
        with pytest.raises(ValidationError):
            LedgerEntry(payload={}, timestamp=datetime(2026, 7, 10))


class DescribeDocument:
    def it_holds_namespace_kind_and_body_with_no_provenance_by_default(self):
        document = Document(namespace="athal7/kb", kind="standing", body="# Notes")

        assert document.namespace == "athal7/kb"
        assert document.kind == "standing"
        assert document.body == "# Notes"
        assert document.provenance is None

    def it_carries_an_optional_provenance_sidecar(self):
        document = Document(
            namespace="athal7/kb",
            kind="dated-archived",
            body="# Archive",
            provenance={"source": "openspec", "archived_at": "2026-07-15"},
        )

        assert document.provenance["source"] == "openspec"

    def it_rejects_a_document_missing_a_body(self):
        with pytest.raises(ValidationError):
            Document(namespace="athal7/kb", kind="standing")
