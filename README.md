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
  - `kb config`: Get and set configuration flags such as the vault `path` (persisted to `~/.config/kb/config.toml`).
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

# Configuration
uv run kb config get path
uv run kb config set path ~/.kb
```

Run `uv run kb --help` for the full list of commands and options.

## Local CQ projection

`kb cq projection` indexes canonical KB records in the configured local CQ
database. It uses the supported `cq` CLI. It does not open or write CQ SQLite
files directly.

The projection supports people, projects, products, decisions, and standing
status records. It turns each record into focused fact units. Long sections
are split. Each fact has a unique CQ identity domain plus entity and alias
domains. `kb` remains the collector and reconciliation engine. CQ is only the
local agent index.

Set `CQ_LOCAL_DB_PATH` to an existing local CQ database file. The projection
fails closed when remote CQ settings, remote authentication, drain mode,
credentials, secrets, or access-incompatible source records are present.

```bash
# Write a non-mutating plan. It is not an apply input yet.
uv run kb cq projection plan --output /tmp/kb-cq-plan.json

# Review the plan, then make an explicit approved manifest.
uv run kb cq projection approve /tmp/kb-cq-plan.json --output /tmp/kb-cq-approved.json

# Apply only the approved manifest.
uv run kb cq projection apply /tmp/kb-cq-approved.json

# Inspect durable external ledger state and validate CQ mappings.
uv run kb cq projection status
uv run kb cq projection verify

# Write a one-time all-scope backfill plan.
uv run kb cq projection backfill --output /tmp/kb-cq-backfill.json
```

The ledger defaults to `~/.local/share/kb/cq-projection-ledger.json`. It stores
source fingerprints, access classification, active and replaced KU IDs, stale
state, per-scope expected-source completion, and recoverable pending operations.
It is outside both the KB vault and CQ. The ledger, plans, and manifests use
owner-only file mode.

Canonical `access` or `classification` frontmatter controls access. The default
for every projection scope is `internal`. Public records must declare
`access: public`. Internal and classified records require
`--authorization-policy all-local-agents` during planning. Approval binds a
digest of the complete manifest, and apply checks it again.

Apply acquires a single-run lock, recovers persisted pending CQ operations, and
then rebuilds the current canonical projection before it makes a new CQ change.
Any changed source, source-set, fragment boundary, access class, or projected
content rejects the approved manifest. Apply records expected sources but does
not mark a scope complete. `verify` performs exact identity and content-marker
retrieval before it marks the verified scopes complete.

Use a LaunchAgent only to run the command and schedule it. Put no projection
workflow logic in launchd configuration.

Requires Python 3.12+.

## Development

```bash
uv run pytest -q
uv run ruff check .
```

---

MIT licensed. See [LICENSE](./LICENSE).
