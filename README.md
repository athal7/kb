# kb

A typed, versioned knowledge base engine and CLI for tracking people, projects, and decisions.

## Why

Personal and team knowledge — who's who, what's happening on which project, past decisions — tends to live as scattered notes that an AI coding agent greps through directly. That works until it doesn't: no validation, no schema, no safe way to write back. `kb` generalizes that pile of notes into an engine that owns the storage format and its invariants, exposing one typed JSON contract so any client (CLI, scripts, an MCP server, a TUI) can read and write safely without ever touching the disk format directly.

## Architecture

- **Engine** — a deterministic library that owns all invariants and the on-disk storage format. Private and opaque; free to change later without breaking anyone.
- **Contract** — the one typed, versioned JSON read/write interface every consumer binds to. This is the public surface, not the disk format.
- **CLI** (`kb`) — the primary transport. Used directly from the shell and by AI coding agents as a cheap, opaque subprocess call.
- **MCP server** — a secondary, speculative transport. Deterministic read/query/resolve only — no sampling or judgment features — deferred until a real MCP-native consumer exists.
- **TUI** — a separate community consumer, binding via the CLI or a direct library link.

## Status

Early scaffold. No implementation yet — see the tracking issues:

- Issue #TBD — CLI + engine (start here)
- Issue #TBD — MCP adapter (deferred)
- Issue #TBD — TUI integration hooks (coordinate with community TUI effort)

## Design principles

- The storage format is a private implementation detail, never a public contract.
- The contract is versioned; additive changes never break older clients.
- Going opaque must not lose grep-like search power — the contract ships a real query/search verb.
- Deterministic-only for the MCP surface — no sampling or elicitation until a concrete need exists.

---

MIT licensed. See [LICENSE](./LICENSE).
