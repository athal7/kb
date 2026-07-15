"""action-items.md parsing and byte-faithful editing.

This is the Phase 1 / Phase 2 seam. Phase 1 only reads, but the parser is round-trip
capable from day one so Phase 2 write-back is additive, not a rewrite. The hard
guarantee: parse -> serialize (no change) must be byte-identical, and toggling one
item must change exactly that item's line and nothing else, so the next kb-enrich run
sees a structurally identical file (zero formatting drift).
"""

from kb.core.actionitems import ActionItemsFile, load_action_items

SAMPLE = """# Open Action Items

## From 2026-07-07 (Slack)
- [ ] **Stephen**: Attend All-MoCo meeting
- [ ] **Team**: sync name updated

## From 2026-07-02 (0din Check-in)
- [x] **Stephen**: Complete Vertex AI deployment — done 2026-07-07
- [ ] **Kate**: Follow up with [[Firefox]] team — see [PR](https://x/1) 0DIN-1732

## Ongoing / Unresolved
- [ ] Venezuela logistics — fluid situation
"""


class DescribeParse:
    def it_groups_items_under_their_source_headers(self):
        f = ActionItemsFile.parse(SAMPLE)

        assert [i.source_group for i in f.items] == [
            "From 2026-07-07 (Slack)",
            "From 2026-07-07 (Slack)",
            "From 2026-07-02 (0din Check-in)",
            "From 2026-07-02 (0din Check-in)",
            "Ongoing / Unresolved",
        ]

    def it_captures_checked_state(self):
        f = ActionItemsFile.parse(SAMPLE)

        checked = [i.checked for i in f.items]
        assert checked == [False, False, True, False, False]

    def it_extracts_bold_person_prefix_when_present(self):
        f = ActionItemsFile.parse(SAMPLE)

        assert f.items[0].person_prefix == "Stephen"
        assert f.items[4].person_prefix is None  # Venezuela item has no bold prefix

    def it_extracts_wikilinks_external_links_and_linear_refs(self):
        f = ActionItemsFile.parse(SAMPLE)
        kate = f.items[3]

        assert kate.wikilinks == ["Firefox"]
        assert kate.external_links == ["https://x/1"]
        assert kate.linear_refs == ["0DIN-1732"]

    def it_does_not_mistake_pr_numbers_or_urls_for_linear_refs(self):
        # Real vault landmine: "PR #986" and "[#986](url)" must not become Linear refs.
        text = (
            "## From X\n"
            "- [ ] Reply to PR #986 (0DIN-1768) — see "
            "[#986](https://github.com/0din-ai/odin/pull/986)\n"
        )

        item = ActionItemsFile.parse(text).items[0]

        assert item.linear_refs == ["0DIN-1768"]
        assert item.external_links == ["https://github.com/0din-ai/odin/pull/986"]

    def it_records_line_numbers_for_each_item(self):
        f = ActionItemsFile.parse(SAMPLE)

        # Every item's raw line must round-trip from its recorded line number.
        original_lines = SAMPLE.split("\n")
        for item in f.items:
            assert original_lines[item.line_no] == item.raw_line


class DescribeRoundTrip:
    def it_serializes_back_to_byte_identical_text(self):
        f = ActionItemsFile.parse(SAMPLE)

        assert f.serialize() == SAMPLE

    def it_preserves_trailing_whitespace_and_blank_lines(self):
        weird = "## From X\n- [ ]   padded item   \n\n\n- [x] done\n"

        assert ActionItemsFile.parse(weird).serialize() == weird

    def it_preserves_a_file_with_no_trailing_newline(self):
        no_nl = "## From X\n- [ ] item"

        assert ActionItemsFile.parse(no_nl).serialize() == no_nl


class DescribeToggle:
    def it_checks_an_unchecked_item_changing_only_that_line(self):
        f = ActionItemsFile.parse(SAMPLE)
        target = f.items[0]  # "- [ ] **Stephen**: Attend All-MoCo meeting"

        f.toggle(target)
        result = f.serialize()

        before = SAMPLE.split("\n")
        after = result.split("\n")
        changed = [i for i in range(len(before)) if before[i] != after[i]]
        assert changed == [target.line_no]
        assert after[target.line_no] == "- [x] **Stephen**: Attend All-MoCo meeting"

    def it_unchecks_a_checked_item(self):
        f = ActionItemsFile.parse(SAMPLE)
        target = f.items[2]  # the "- [x] ..." Vertex item

        f.toggle(target)

        assert f.serialize().split("\n")[target.line_no].startswith("- [ ]")

    def it_reflects_toggle_in_the_item_model(self):
        f = ActionItemsFile.parse(SAMPLE)
        target = f.items[0]

        f.toggle(target)

        assert target.checked is True


class DescribeLoadActionItems:
    """The refresh seam: re-reading action-items.md from disk on demand.

    Both the CLI entry point (build_app()) and the dashboard's refresh action
    need to load the same file the same way, so this lives in core rather than
    being duplicated in __main__.py and ui/app.py.
    """

    def it_parses_items_from_the_action_items_file_in_kb_root(self, tmp_path):
        (tmp_path / "action-items.md").write_text(SAMPLE, encoding="utf-8")

        items = load_action_items(tmp_path)

        assert [i.source_group for i in items][:2] == [
            "From 2026-07-07 (Slack)",
            "From 2026-07-07 (Slack)",
        ]

    def it_returns_an_empty_list_when_the_file_does_not_exist(self, tmp_path):
        assert load_action_items(tmp_path) == []

    def it_reflects_changes_written_to_disk_between_calls(self, tmp_path):
        path = tmp_path / "action-items.md"
        path.write_text("## From X\n- [ ] first\n", encoding="utf-8")
        first_call = load_action_items(tmp_path)

        path.write_text("## From X\n- [ ] first\n- [ ] second\n", encoding="utf-8")
        second_call = load_action_items(tmp_path)

        assert len(first_call) == 1
        assert len(second_call) == 2
