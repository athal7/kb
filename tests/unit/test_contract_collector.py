"""Unit tests for collector contract models and their translations."""

import pytest
from pydantic import ValidationError

from kb.contract import (
    ActionItem,
    Decision,
    JournalEntry,
    MeetingNote,
    PersonMention,
    Section,
    action_item_to_core,
    contract_schema,
    decision_from_core,
    decision_to_core,
    journal_entry_from_core,
    journal_entry_to_core,
    meeting_note_to_core,
    person_mention_from_core,
    person_mention_to_core,
)
from kb.core.actionitems import ActionItem as CoreActionItem
from kb.core.markdown import Section as CoreSection
from kb.core.models import (
    Decision as CoreDecision,
    JournalEntry as CoreJournalEntry,
    Person as CorePerson,
)


class DescribeCollectorActionItem:
    def it_validates_correct_inputs(self):
        item = ActionItem(
            text="Sync on Firebase",
            checked=True,
            person_prefix="Kate",
            source_group="Slack",
            wikilinks=["Firebase"],
            external_links=["https://firebase.google.com"],
            linear_refs=["FIRE-1"],
        )
        assert item.text == "Sync on Firebase"
        assert item.checked is True
        assert item.person_prefix == "Kate"
        assert item.source_group == "Slack"
        assert item.wikilinks == ["Firebase"]
        assert item.external_links == ["https://firebase.google.com"]
        assert item.linear_refs == ["FIRE-1"]

    def it_ignores_extra_fields(self):
        item = ActionItem(text="Task", unknown_field="ignored")
        assert not hasattr(item, "unknown_field")

    def it_raises_validation_error_on_missing_required_fields(self):
        with pytest.raises(ValidationError):
            ActionItem()  # text is required


class DescribeCollectorDecision:
    def it_validates_correct_inputs(self):
        dec = Decision(
            title="Adopt SQLite",
            date="2026-07-16",
            status="accepted",
            deciders=["Stephen", "Kate"],
            body="Use SQLite for storage.",
            sections=[Section(heading="Rationale", body="It is serverless.")],
        )
        assert dec.title == "Adopt SQLite"
        assert dec.date == "2026-07-16"
        assert dec.status == "accepted"
        assert dec.deciders == ["Stephen", "Kate"]
        assert dec.body == "Use SQLite for storage."
        assert dec.sections[0].heading == "Rationale"


class DescribeCollectorJournalEntry:
    def it_validates_correct_inputs(self):
        entry = JournalEntry(
            date="2026-07-16",
            body="Productive day.",
            sections=[Section(heading="Highlights", body="Fixed the bug.")],
            wikilinks=["Obsidian"],
        )
        assert entry.date == "2026-07-16"
        assert entry.body == "Productive day."
        assert entry.sections[0].heading == "Highlights"
        assert entry.wikilinks == ["Obsidian"]


class DescribeCollectorMeetingNote:
    def it_validates_correct_inputs(self):
        note = MeetingNote(
            title="Design Sync",
            date="2026-07-16",
            participants=["Stephen", "Kate"],
            body="Discussed SQLite.",
            sections=[Section(heading="Next Steps", body="Create schemas.")],
            wikilinks=["SQLite"],
        )
        assert note.title == "Design Sync"
        assert note.participants == ["Stephen", "Kate"]
        assert note.sections[0].heading == "Next Steps"


class DescribeCollectorPersonMention:
    def it_validates_correct_inputs(self):
        mention = PersonMention(
            name="ksilverstein",
            email="k@example.com",
            slack_id="U123",
            team="Engineering",
            title="Director",
            aliases=["Kate"],
            context="Mentioned by Stephen",
            source="Slack",
        )
        assert mention.name == "ksilverstein"
        assert mention.email == "k@example.com"
        assert mention.slack_id == "U123"
        assert mention.team == "Engineering"
        assert mention.title == "Director"
        assert mention.aliases == ["Kate"]
        assert mention.context == "Mentioned by Stephen"
        assert mention.source == "Slack"


class DescribeContractSchemaWithCollector:
    def it_includes_collector_schemas(self):
        schema = contract_schema()
        for key in ["ActionItem", "Decision", "JournalEntry", "MeetingNote", "PersonMention"]:
            assert key in schema
            assert schema[key]["type"] == "object"


class DescribeCollectorTranslation:
    def it_translates_action_item_to_core(self):
        item = ActionItem(
            text="Do task",
            checked=True,
            person_prefix="Kate",
            source_group="Standup",
            wikilinks=["Odin"],
            external_links=["http://x"],
            linear_refs=["ODIN-1"],
        )
        core = action_item_to_core(item)

        assert isinstance(core, CoreActionItem)
        assert core.text == "Do task"
        assert core.checked is True
        assert core.person_prefix == "Kate"
        assert core.source_group == "Standup"
        assert core.wikilinks == ["Odin"]
        assert core.external_links == ["http://x"]
        assert core.linear_refs == ["ODIN-1"]
        assert core.raw_line == "- [x] **Kate**: Do task"
        assert core.line_no == -1

    def it_translates_decision_bidirectionally(self):
        # Collector to Core
        dec = Decision(
            title="Adopt SQLite",
            date="2026-07-16",
            body="Use SQLite.",
            sections=[Section(heading="Rationale", body="Serverless.")],
        )
        core = decision_to_core(dec, "decisions/sqlite.md")

        assert isinstance(core, CoreDecision)
        assert core.file == "decisions/sqlite.md"
        assert not core.is_readonly
        assert len(core.sections) == 2
        assert core.sections[0].heading is None
        assert core.sections[0].body == "Use SQLite."
        assert core.sections[1].heading == "Rationale"
        assert core.sections[1].body == "Serverless."

        # Core back to Collector
        back = decision_from_core(core)
        assert isinstance(back, Decision)
        assert back.title == "sqlite"
        assert back.body == "Use SQLite."
        assert len(back.sections) == 1
        assert back.sections[0].heading == "Rationale"
        assert back.sections[0].body == "Serverless."

    def it_translates_journal_entry_bidirectionally(self):
        # Collector to Core
        entry = JournalEntry(
            date="2026-07-16",
            body="Awesome day.",
            sections=[Section(heading="Work", body="Coding.")],
            wikilinks=["Obsidian"],
        )
        core = journal_entry_to_core(entry, "journal/2026-07-16.md")

        assert isinstance(core, CoreJournalEntry)
        assert core.file == "journal/2026-07-16.md"
        assert core.date == "2026-07-16"
        assert len(core.sections) == 2
        assert core.sections[0].heading is None
        assert core.sections[0].body == "Awesome day."
        assert core.sections[1].heading == "Work"
        assert core.sections[1].body == "Coding."
        assert len(core.wikilinks) == 1
        assert core.wikilinks[0].raw_text == "Obsidian"

        # Core back to Collector
        back = journal_entry_from_core(core)
        assert isinstance(back, JournalEntry)
        assert back.date == "2026-07-16"
        assert back.body == "Awesome day."
        assert len(back.sections) == 1
        assert back.sections[0].heading == "Work"
        assert back.sections[0].body == "Coding."
        assert back.wikilinks == ["Obsidian"]

    def it_translates_meeting_note_to_core(self):
        note = MeetingNote(
            title="Design Sync",
            date="2026-07-16",
            participants=["Stephen", "Kate"],
            body="Review SQLite.",
            sections=[Section(heading="Next Steps", body="Schema.")],
            wikilinks=["SQLite"],
        )
        core = meeting_note_to_core(note, "journal/2026-07-16.md")

        assert isinstance(core, CoreJournalEntry)
        assert core.file == "journal/2026-07-16.md"
        assert core.date == "2026-07-16"
        assert len(core.sections) == 2
        assert core.sections[0].heading is None
        assert core.sections[0].body == "Review SQLite."
        assert core.sections[1].heading == "Next Steps"
        assert core.sections[1].body == "Schema."
        assert len(core.wikilinks) == 1
        assert core.wikilinks[0].raw_text == "SQLite"

    def it_translates_person_mention_bidirectionally(self):
        # Collector to Core
        mention = PersonMention(
            name="ksilverstein",
            email="k@example.com",
            slack_id="U123",
            team="Engineering",
            title="Director",
            aliases=["Kate"],
            context="Active member.",
        )
        core = person_mention_to_core(mention, "people/ksilverstein.md")

        assert isinstance(core, CorePerson)
        assert core.file == "people/ksilverstein.md"
        assert core.email == "k@example.com"
        assert core.slack_id == "U123"
        assert core.team == "Engineering"
        assert core.title == "Director"
        assert core.aliases == ["Kate"]
        assert core.frontmatter == {
            "email": "k@example.com",
            "slack_id": "U123",
            "team": "Engineering",
            "title": "Director",
            "aliases": ["Kate"],
        }
        assert len(core.sections) == 1
        assert core.sections[0].heading == "Context"
        assert core.sections[0].body == "Active member."

        # Core back to Collector
        back = person_mention_from_core(core)
        assert isinstance(back, PersonMention)
        assert back.name == "ksilverstein"
        assert back.email == "k@example.com"
        assert back.slack_id == "U123"
        assert back.team == "Engineering"
        assert back.title == "Director"
        assert back.aliases == ["Kate"]
        assert back.context == "Active member."
