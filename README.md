# kb

A personal/team knowledge base: people, projects, decisions, and journal notes, browsed and managed through a terminal dashboard.

## Status

This repo currently hosts a working Python implementation — a dashboard TUI with a growing CLI surface, unified under one `kb` entry point (`opencode`-style: bare `kb` launches the interactive dashboard; subcommands will handle scriptable, AI-facing operations as they're added). This is the foundation going forward, per the discussion on [issue #3](https://github.com/athal7/kb/issues/3).

What works today:

- A dashboard with an action-items pane, fuzzy person search (`/`), vim-style `:` command bar, and keybindings for navigating panes.
- A plugin system: panes are registered rather than hardcoded, and layout is driven by `~/.config/kb/config.toml`. Calendar/reminders integration lives behind this plugin boundary rather than shipping as a core pane.
- ~239 tests, built TDD-first (`uv run pytest`), ruff-clean.

What's not done yet:

- No CLI subcommands beyond the bare TUI launch — `kb` opens the dashboard; there's no scriptable read/write surface yet.
- The vault-parsing code (`src/kb/core/`) is a working direct-to-markdown implementation, not yet refactored toward the Engine/Contract shape defined in [`openspec/specs/domain-model/spec.md`](./openspec/specs/domain-model/spec.md) and [`openspec/specs/kb-contract/spec.md`](./openspec/specs/kb-contract/spec.md). That refactor is future work, not this PR.

### Open discussion point: the TypeScript scaffold

`packages/{engine,cli,mcp-server}` are the original TypeScript scaffold. Per the issue #3 discussion, the intent is to retire that scaffold in favor of this Python codebase — but that's not resolved yet. This PR is meant to surface that discussion, not settle it unilaterally, so the TS packages are left in place pending removal or reconciliation.

## Running it

```
uv sync
uv run kb
```

Requires Python 3.12+.

## Development

```
uv run pytest -q
uv run ruff check .
```

---

MIT licensed. See [LICENSE](./LICENSE).
