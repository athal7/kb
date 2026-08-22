# kb

A personal/team knowledge base: people, projects, decisions, action items, and journal notes, browsed and managed through a terminal dashboard and scriptable CLI.

## Status

This repo hosts a Python implementation — an interactive dashboard TUI and a rich CLI surface, unified under one `kb` entry point (`opencode`-style: bare `kb` launches the interactive dashboard; subcommands handle scriptable, AI-facing, and automation workflows).

What works today:

- **Interactive TUI Dashboard**: Features an action-items pane, fuzzy search (`/`), vim-style command bar (`:`), vault summary, pane navigation keybindings, and custom layout configuration via `~/.config/kb/config.toml`.
- **Plugin Architecture**: Modular plugin architecture where core and external panes (such as macOS Calendar/Reminders integration) are registered through a clean `PaneSpec` plugin boundary.
- **Full CLI Command Surface**: Command groups for querying and managing vault entities:
  - `kb people`: List and show people entries and alias lookups.
  - `kb projects`: List and show project entries.
  - `kb products`: List and show product entries.
  - `kb journal`: List, show, and append sections to daily journal notes.
  - `kb action-items`: List open/in-progress items and mutate status (`todo`, `progress`, `complete`).
  - `kb openspec`: List, show, and import archived OpenSpec changes and standing specs.
- **Contract Boundary Layer**: Formal contract layer (`kb.contract`) providing standardized schemas and error envelopes, insulating the core vault engine (`kb.core`) from external transport requirements and CLI consumers.
- **Reference Collectors**: Opt-in collector scripts (such as `collectors/git_activity.py`) for gathering external activity data.
- **High Test Coverage**: 400+ unit and integration tests (`uv run pytest`), TDD-built, and ruff-clean.

### Open discussion point: the TypeScript scaffold

`packages/{engine,cli,mcp-server}` contain the original TypeScript scaffold. The intent is to retire that scaffold in favor of this Python codebase — pending final removal or reconciliation.

## Running it

```bash
uv sync
uv run kb
```

`kb` with no arguments launches the interactive TUI dashboard.

It also serves as a scriptable CLI with `--format [json|text|auto]` support:

```bash
# Querying people, projects, and products
uv run kb people list
uv run kb people show "Jane Doe"
uv run kb projects list
uv run kb products list

# Journal entry management
uv run kb journal list
uv run kb journal show 2025-01-15
uv run kb journal append --section "Notes" "Discussed architecture updates."

# Action item management
uv run kb action-items list
uv run kb action-items complete "Task ID or description"

# OpenSpec queries
uv run kb openspec list
uv run kb openspec specs
```

Run `uv run kb --help` for the full list of commands and options.

Requires Python 3.12+.

## Development

```bash
uv run pytest -q
uv run ruff check .
```

---

MIT licensed. See [LICENSE](./LICENSE).
