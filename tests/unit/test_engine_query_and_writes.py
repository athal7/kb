"""Unit and integration tests for the KB Engine's query and write operations.

These tests assert contract conformance, write invariants (section caps, relationship symmetry,
alias sync), and query capabilities using the anonymized fixtures.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from kb.contract.collector import JournalEntry
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

        # Searching for "gRPC" which is in Marcus Webb's section body
        req = QueryRequest(text="gRPC")
        resp = engine.query(req)

        assert resp.ok is True
        assert len(resp.data.hits) > 0
        hit = resp.data.hits[0]
        assert hit.ref == "people/marcus-webb"
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
        assert any(hit.ref == "projects/lumen-sentinel" for hit in resp.data.hits)
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

        # Traversal: projects related to "people/marcus-webb"
        req = QueryRequest(
            related_to="people/marcus-webb",
            relationship="projects"
        )
        resp = engine.query(req)

        assert resp.ok is True
        assert len(resp.data.hits) > 0
        refs = [h.ref for h in resp.data.hits]
        assert "projects/lumen-sentinel" in refs

    def it_supports_relationship_traversal_incoming(self):
        engine = Engine(VAULT)

        # Traversal: people on project "projects/lumen-sentinel"
        req = QueryRequest(
            related_to="projects/lumen-sentinel",
            relationship="people"
        )
        resp = engine.query(req)

        assert resp.ok is True
        assert len(resp.data.hits) > 0
        refs = [h.ref for h in resp.data.hits]
        assert "people/diego-ruiz" in refs or "people/marcus-webb" in refs

    def it_resolves_alias_aware_query_terms(self):
        engine = Engine(VAULT)

        # "mwebb" is an alias of "Marcus Webb"
        req = QueryRequest(text="mwebb", collections=["people"])
        resp = engine.query(req)

        assert resp.ok is True
        assert len(resp.data.hits) > 0
        refs = [h.ref for h in resp.data.hits]
        assert "people/marcus-webb" in refs


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

    def it_returns_io_error_when_lock_acquisition_fails_with_non_contention_oserror(
        self, temp_vault, monkeypatch
    ):
        engine = Engine(temp_vault)

        profile = Profile(
            ref="people/lock-error-test",
            kind="person",
            fields={"email": "lock-error@example.com"},
            sections=[Section(heading="Lock Error Test", body="- something")],
        )

        def raise_permission_error(*args, **kwargs):
            raise PermissionError("simulated permission failure")

        # os.open (which creates the lock file via O_CREAT|O_EXCL) succeeds, but
        # the subsequent os.fdopen fails with something other than
        # FileExistsError. That must not retry or propagate — it should be
        # reported as a structured io error, and the lock file it created must
        # not be left behind.
        monkeypatch.setattr(os, "fdopen", raise_permission_error)

        resp = engine.write_profile(profile)

        assert resp.ok is False
        assert resp.error.code.startswith("io.")
        assert not (temp_vault / ".kb.lock").is_file()

    def it_syncs_bidirectional_relationships_upon_write(self, temp_vault):
        engine = Engine(temp_vault)

        # Elena (people/elena) has no relationship to projects/atlas initially
        # Let's save Elena with a relationship pointing to projects/atlas
        elena = engine._get_indexed_profile("people/elena")
        assert elena is not None
        assert len(elena.relationships) == 0

        # Add projects relationship pointing to projects/atlas
        elena.relationships.append(
            Relationship(name="projects", target="projects/atlas")
        )

        resp = engine.write_profile(elena)
        assert resp.ok is True

        # Reload target and verify that projects/atlas got the inverse
        # 'people' relationship back to Elena
        atlas = engine._get_indexed_profile("projects/atlas")
        assert atlas is not None
        has_inverse = any(
            r.name == "people" and r.target == "people/elena"
            for r in atlas.relationships
        )
        assert has_inverse is True

    def it_syncs_aliases_to_the_resolution_map(self, temp_vault):
        engine = Engine(temp_vault)

        # Save a person with new aliases
        priya = engine._get_indexed_profile("people/panand")
        assert priya is not None

        priya.fields["aliases"] = ["Priyaa", "pnand"]
        resp = engine.write_profile(priya)
        assert resp.ok is True

        # Read names.json and assert the aliases exist
        names_json = json.loads((temp_vault / "names.json").read_text(encoding="utf-8"))
        assert names_json["Priyaa"] == "Priya Anand"
        assert names_json["pnand"] == "Priya Anand"
        # Old aliases not in the list should be cleaned up
        assert "priya" not in names_json

    def it_removes_stale_alias_map_entries_after_profile_rename(self, temp_vault):
        engine = Engine(temp_vault)

        # Title matches the slug-derived heading so it round-trips through
        # serialization as the H1 (see `_serialize_profile_to_markdown`).
        original = Profile(
            ref="people/rename-test",
            kind="person",
            fields={"email": "rename@example.com", "aliases": ["OldAlias"]},
            sections=[Section(heading="Rename Test", body="- something")],
        )
        resp = engine.write_profile(original)
        assert resp.ok is True

        names_json = json.loads((temp_vault / "names.json").read_text(encoding="utf-8"))
        assert names_json["OldAlias"] == "Rename Test"

        # Rename: change the title and swap the alias.
        renamed = engine._get_indexed_profile("people/rename-test")
        assert renamed is not None
        renamed.sections[0].heading = "New Name"
        renamed.fields["aliases"] = ["NewAlias"]

        resp2 = engine.write_profile(renamed)
        assert resp2.ok is True

        names_json_after = json.loads((temp_vault / "names.json").read_text(encoding="utf-8"))
        assert "OldAlias" not in names_json_after
        assert all(v != "Rename Test" for v in names_json_after.values())
        assert names_json_after["NewAlias"] == "New Name"

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


class DescribeEngineJournalWrites:
    def it_creates_a_new_journal_file_with_h1_and_body(self, temp_vault):
        engine = Engine(temp_vault)

        resp = engine.write_journal_entry(
            JournalEntry(date="2026-07-15", body="Some test content")
        )

        assert resp.ok is True
        created = temp_vault / "journal" / "2026-07-15.md"
        assert created.read_text(encoding="utf-8") == "# 2026-07-15\n\nSome test content\n"
        assert not (temp_vault / ".kb.lock").is_file()

    def it_creates_a_new_journal_under_a_section(self, temp_vault):
        engine = Engine(temp_vault)

        resp = engine.write_journal_entry(
            JournalEntry(
                date="2026-07-15",
                sections=[Section(heading="Git Activity", body="- commit 1")],
            )
        )

        assert resp.ok is True
        content = (temp_vault / "journal" / "2026-07-15.md").read_text(encoding="utf-8")
        assert content == "# 2026-07-15\n\n## Git Activity\n- commit 1\n"

    def it_appends_to_an_existing_section(self, temp_vault):
        engine = Engine(temp_vault)
        journal_file = temp_vault / "journal" / "2026-07-15.md"
        journal_file.write_text(
            "# 2026-07-15\n\n## Git Activity\n- commit 1\n", encoding="utf-8"
        )

        resp = engine.write_journal_entry(
            JournalEntry(
                date="2026-07-15",
                sections=[Section(heading="Git Activity", body="- commit 2")],
            )
        )

        assert resp.ok is True
        content = journal_file.read_text(encoding="utf-8")
        assert content == "# 2026-07-15\n\n## Git Activity\n- commit 1\n\n- commit 2\n"

    def it_creates_a_missing_section_in_an_existing_journal(self, temp_vault):
        engine = Engine(temp_vault)
        journal_file = temp_vault / "journal" / "2026-07-15.md"
        journal_file.write_text(
            "# 2026-07-15\n\n## Slack Context\n- discussion\n", encoding="utf-8"
        )

        resp = engine.write_journal_entry(
            JournalEntry(
                date="2026-07-15",
                sections=[Section(heading="Git Activity", body="- commit 1")],
            )
        )

        assert resp.ok is True
        content = journal_file.read_text(encoding="utf-8")
        assert content == (
            "# 2026-07-15\n\n"
            "## Slack Context\n- discussion\n\n"
            "## Git Activity\n- commit 1\n"
        )

    def it_rejects_an_invalid_date_and_writes_nothing(self, temp_vault):
        engine = Engine(temp_vault)

        resp = engine.write_journal_entry(
            JournalEntry(date="invalid-date", body="stuff")
        )

        assert resp.ok is False
        assert resp.error.code == "validation.invalid_date"
        assert resp.error.path == "/date"
        assert not (temp_vault / "journal" / "invalid-date.md").is_file()

    def it_rejects_a_traversing_date(self, temp_vault):
        engine = Engine(temp_vault)

        resp = engine.write_journal_entry(
            JournalEntry(date="../evil", body="stuff")
        )

        assert resp.ok is False
        assert not (temp_vault / "evil.md").is_file()

    def it_cleans_up_the_lock_on_non_contention_oserror(self, temp_vault, monkeypatch):
        engine = Engine(temp_vault)

        def raise_permission_error(*args, **kwargs):
            raise PermissionError("simulated permission failure")

        monkeypatch.setattr(os, "fdopen", raise_permission_error)

        resp = engine.write_journal_entry(
            JournalEntry(date="2026-07-15", body="content")
        )

        assert resp.ok is False
        assert resp.error.code.startswith("io.")
        assert not (temp_vault / ".kb.lock").is_file()
