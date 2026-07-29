"""Tolerant frontmatter splitting.

The vault mixes files with YAML frontmatter (people/projects/products) and files
with none at all (journal/decisions). Malformed YAML in a human-written vault is
expected drift, not an exceptional condition. `split` must never raise.
"""

from kb.core.frontmatter import split


class DescribeSplit:
    def it_parses_frontmatter_and_returns_body(self):
        text = "---\ntype: person\nemail: a@b.com\n---\n# Title\nbody line\n"

        result = split(text)

        assert result.frontmatter == {"type": "person", "email": "a@b.com"}
        assert result.body == "# Title\nbody line\n"
        assert result.warning is None

    def it_returns_none_frontmatter_when_absent(self):
        text = "# 2026-07-13\n\n## Lumen\n- did a thing\n"

        result = split(text)

        assert result.frontmatter is None
        assert result.body == text
        assert result.warning is None

    def it_returns_warning_and_none_frontmatter_when_yaml_is_malformed(self):
        text = "---\ntype: person\n  bad: : indent:\n---\n# Title\n"

        result = split(text)

        assert result.frontmatter is None
        assert result.body == "# Title\n"
        assert result.warning is not None

    def it_treats_non_mapping_frontmatter_as_a_warning(self):
        # A frontmatter block that parses to a list/scalar, not a dict, is drift.
        text = "---\n- just\n- a list\n---\nbody\n"

        result = split(text)

        assert result.frontmatter is None
        assert result.warning is not None
        assert result.body == "body\n"

    def it_handles_empty_frontmatter_block_as_empty_mapping(self):
        text = "---\n---\nbody\n"

        result = split(text)

        assert result.frontmatter == {}
        assert result.body == "body\n"
        assert result.warning is None
