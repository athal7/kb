"""Turning raw vault files into domain models.

The parse layer sits on top of frontmatter-splitting and markdown-sectioning: it maps
a file's text to a Person / Project / Product / JournalEntry / Decision. It absorbs the
vault's real-world drift so nothing downstream has to:

  - `slack:` vs `slack_id:` — the SKILL doc says `slack`, real files use `slack_id`;
    both must land in one `slack_id` field.
  - Frontmatter may be entirely absent (journal, decisions) — parsing must not raise.
  - Relationship list fields (e.g. `projects`) hold wikilink strings (`"[[Priya]]"`) that
    must be unwrapped to raw targets for later resolution, tolerating stray
    brackets/whitespace; alias lists hold bare strings and pass through unchanged.
  - Journals have no fixed heading schema and no frontmatter; the H1 date is the identity.
"""

from kb.core import parse
from kb.core.models import Decision, JournalEntry, Person, Product, Project


class DescribeParsePerson:
    def it_reads_core_frontmatter_fields(self):
        text = (
            "---\n"
            "type: person\n"
            "email: k@example.com\n"
            "team: Research\n"
            "title: ML Researcher\n"
            "aliases:\n  - Priya\n"
            "---\n"
            "# Priya Anand\n"
        )

        person = parse.parse_person(text, file="people/panand.md")

        assert isinstance(person, Person)
        assert person.email == "k@example.com"
        assert person.team == "Research"
        assert person.title == "ML Researcher"
        assert person.aliases == ["Priya"]

    def it_normalizes_slack_id_drift_from_documented_slack_key(self):
        # SKILL doc says `slack:`; some files use it, others use `slack_id:`. Unify.
        via_slack = parse.parse_person(
            "---\nslack: U0DRIFT\n---\n# X\n", file="people/x.md"
        )
        via_slack_id = parse.parse_person(
            "---\nslack_id: U0CANON\n---\n# Y\n", file="people/y.md"
        )

        assert via_slack.slack_id == "U0DRIFT"
        assert via_slack_id.slack_id == "U0CANON"

    def it_unwraps_project_wikilinks_from_frontmatter(self):
        text = (
            "---\n"
            'projects:\n  - "[[Sentinel]]"\n  - "[[Lumen]]"\n'
            "---\n# Person\n"
        )

        person = parse.parse_person(text, file="people/p.md")

        assert [link.raw_text for link in person.project_links] == ["Sentinel", "Lumen"]

    def it_tolerates_absent_frontmatter_without_raising(self):
        person = parse.parse_person("# Just A Body\nno frontmatter here\n", file="people/p.md")

        assert person.email is None
        assert person.aliases == []
        assert person.project_links == []

    def it_captures_body_sections(self):
        text = "---\ntype: person\n---\n# Name\n## Current\n- doing things\n## Style\n- terse\n"

        person = parse.parse_person(text, file="people/p.md")

        headings = [s.heading for s in person.sections]
        assert "Current" in headings
        assert "Style" in headings


class DescribeParseProject:
    def it_reads_status_and_optional_fields(self):
        text = (
            "---\n"
            "type: project\n"
            "status: active\n"
            "github: lumen-labs/lumen\n"
            "linear: https://linear.app/x\n"
            'product: "[[LUMEN]]"\n'
            'people:\n  - "[[Diego Ruiz]]"\n'
            "---\n# Sentinel\n## Status\n- active\n"
        )

        project = parse.parse_project(text, file="projects/lumen-sentinel.md")

        assert isinstance(project, Project)
        assert project.status == "active"
        assert project.github == "lumen-labs/lumen"
        assert project.linear == "https://linear.app/x"
        assert project.product_link is not None
        assert project.product_link.raw_text == "LUMEN"
        assert [link.raw_text for link in project.people_links] == ["Diego Ruiz"]

    def it_leaves_product_link_none_when_absent(self):
        project = parse.parse_project(
            "---\ntype: project\nstatus: blocked\n---\n# W\n", file="projects/w.md"
        )

        assert project.product_link is None
        assert project.status == "blocked"


class DescribeParseProduct:
    def it_reads_repos_and_linear_label(self):
        text = (
            "---\n"
            "type: product\n"
            "status: active\n"
            "repos:\n  - lumen\n  - scanner\n"
            "linear: label:lumen.ai\n"
            "aliases:\n  - LUMEN\n"
            "---\n# LUMEN\n"
        )

        product = parse.parse_product(text, file="products/lumen.md")

        assert isinstance(product, Product)
        assert product.repos == ["lumen", "scanner"]
        assert product.linear_label == "label:lumen.ai"
        assert product.aliases == ["LUMEN"]


class DescribeParseJournal:
    def it_takes_the_h1_date_as_identity(self):
        text = "# 2026-07-13\n## Meetings\n- sync with [[Priya]]\n"

        entry = parse.parse_journal(text, file="journal/2026-07-13.md")

        assert isinstance(entry, JournalEntry)
        assert entry.date == "2026-07-13"

    def it_falls_back_to_the_filename_date_when_h1_absent(self):
        # A journal without the leading H1 still has a date in its path.
        entry = parse.parse_journal("no heading here\n", file="journal/2026-07-13.md")

        assert entry.date == "2026-07-13"

    def it_collects_wikilinks_across_the_body(self):
        text = "# 2026-07-13\n## Meetings\n- [[Priya]] and [[Marcus]]\n## Slack\n- [[Lumen]]\n"

        entry = parse.parse_journal(text, file="journal/2026-07-13.md")

        assert [w.raw_text for w in entry.wikilinks] == ["Priya", "Marcus", "Lumen"]

    def it_keeps_variant_headings_as_sections(self):
        text = "# 2026-07-12\n## Slack Context\n- a\n## Diff Stats Summary\n| a | b |\n"

        entry = parse.parse_journal(text, file="journal/2026-07-12.md")

        headings = [s.heading for s in entry.sections]
        assert headings == ["Slack Context", "Diff Stats Summary"]


class DescribeParseDecision:
    def it_flags_archive_as_readonly(self):
        archive = parse.parse_decision("# Archive\n- old\n", file="decisions/archive.md")
        crosscut = parse.parse_decision("# X\n- new\n", file="decisions/cross-cutting.md")

        assert isinstance(archive, Decision)
        assert archive.is_readonly is True
        assert crosscut.is_readonly is False
