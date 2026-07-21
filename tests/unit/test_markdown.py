"""Markdown body parsing: heading-agnostic sections + checkbox items.

Journal files use variant `##` headings that differ day to day (`## Odin`,
`## Warden`, `## Meetings`) and often lack any given section. The parser must
never assume a specific heading exists; it splits whatever headings are present
into an ordered list and lets callers look one up optionally.
"""

from kb.core.markdown import find_wikilinks, parse_checkboxes, split_sections


class DescribeSplitSections:
    def it_splits_body_into_ordered_sections_by_heading(self):
        body = "# Title\nintro line\n## Alpha\na1\na2\n## Beta\nb1\n"

        sections = split_sections(body)

        assert [s.heading for s in sections] == ["Title", "Alpha", "Beta"]
        assert [s.level for s in sections] == [1, 2, 2]
        assert sections[1].body == "a1\na2"
        assert sections[2].body == "b1"

    def it_captures_preamble_before_any_heading_as_a_headingless_section(self):
        body = "loose text\nmore text\n## Alpha\na1\n"

        sections = split_sections(body)

        assert sections[0].heading is None
        assert sections[0].body == "loose text\nmore text"
        assert sections[1].heading == "Alpha"

    def it_returns_empty_list_for_empty_body(self):
        assert split_sections("") == []
        assert split_sections("\n\n") == []

    def it_preserves_subsection_levels(self):
        body = "## Shipped\n### PR one\nx\n### PR two\ny\n"

        sections = split_sections(body)

        assert [(s.heading, s.level) for s in sections] == [
            ("Shipped", 2),
            ("PR one", 3),
            ("PR two", 3),
        ]

    def it_does_not_treat_hash_inside_code_or_text_as_heading(self):
        # A '#' not at column zero is not an ATX heading.
        body = "## Real\ntext with # not a heading\n  ## indented not heading\n"

        sections = split_sections(body)

        assert [s.heading for s in sections] == ["Real"]
        assert "not a heading" in sections[0].body


class DescribeParseCheckboxes:
    def it_parses_unchecked_and_checked_items_with_line_numbers(self):
        body = "- [ ] do a thing\n- [x] did another\nplain bullet\n"

        items = parse_checkboxes(body)

        assert len(items) == 2
        assert items[0].checked is False
        assert items[0].text == "do a thing"
        assert items[0].line_no == 0
        assert items[1].checked is True
        assert items[1].text == "did another"
        assert items[1].line_no == 1

    def it_preserves_the_exact_raw_line_for_byte_faithful_editing(self):
        body = "- [ ]   spaced out   \n"

        items = parse_checkboxes(body)

        assert items[0].raw_line == "- [ ]   spaced out   "

    def it_accepts_uppercase_x_as_checked(self):
        items = parse_checkboxes("- [X] done\n")

        assert items[0].checked is True

    def it_ignores_non_checkbox_lines(self):
        assert parse_checkboxes("just text\n## heading\n- bullet\n") == []


class DescribeFindWikilinks:
    def it_finds_all_wikilink_targets_with_line_numbers(self):
        body = "see [[Kate]] and [[Odin]]\nand [[Josh Porter]] too\n"

        links = find_wikilinks(body)

        assert [(w.raw_text, w.line_no) for w in links] == [
            ("Kate", 0),
            ("Odin", 0),
            ("Josh Porter", 1),
        ]

    def it_returns_empty_when_no_wikilinks(self):
        assert find_wikilinks("no links here\n") == []
