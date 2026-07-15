## Why

Issue #1 asks for a CLI + engine implementation of `kb`, but the whole point of the architecture is that every consumer (CLI, MCP server, TUI, future transports) binds to one typed Contract instead of the on-disk format. That Contract, and the domain vocabulary it's built from, has to be settled in writing before any implementation code exists — otherwise the engine and CLI tracks will independently invent incompatible shapes, and the storage migration (grep-able flat files today → an opaque format later) will have no fixed target to migrate toward. This change is Deliverable 0 of issue #1: a documentation-only spec that everything else binds to.

## What Changes

- Define the four core domain primitives (Engine, Contract, Transport, Collection/Profile) plus the supporting primitives (Resolution map, Ledger, Document store, Schema pack) that the engine's data model is built from.
- Define the JSON Contract that every Transport (CLI, MCP server) speaks: response envelope shape, a stable namespaced error-code enum, semver-based Contract versioning rules, atomic invariant-checked write semantics, the `query` operation's required capabilities, and the CLI transport's stdout/stderr contract.
- No code changes. `packages/engine`, `packages/cli`, and `packages/mcp-server` remain empty stubs; this change produces only markdown specs under `openspec/specs/`.

## Capabilities

### New Capabilities
- `domain-model`: the vocabulary and invariants for Engine, Contract, Transport, Collection, Profile, Resolution map, Ledger, Document store, and Schema pack — the terms every other spec and every implementation track is written against.
- `kb-contract`: the versioned JSON request/response Contract itself — envelope shape, error codes, versioning/compatibility rules, atomic write guarantees, the query/search operation, and the CLI transport's stdout/stderr behavior.

### Modified Capabilities
(none — this is a greenfield repo with no existing specs)

## Impact

- Affected: none at the code level. This change only adds `openspec/specs/domain-model/spec.md` and `openspec/specs/kb-contract/spec.md`.
- Downstream: every subsequent deliverable in issue #1 (engine implementation, CLI implementation) and any future MCP server or TUI work must implement against these two specs rather than inventing their own contract shape.
