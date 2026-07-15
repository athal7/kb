## Context

`kb` is a personal knowledge base tool being generalized from an existing pile of hand-maintained markdown/JSON files (people, products, projects, decisions, journal, resolution maps like `names.json`) into a proper engine + contract + transport architecture. Issue #1 covers the CLI + engine track. Before any of that code is written, the vocabulary the engine's data model is built from (Engine, Contract, Transport, Collection, Profile, and the supporting primitives) and the Contract itself (the JSON shape every Transport speaks) need to be nailed down, because:

- The on-disk format is explicitly planned to change (flat markdown+JSON today, possibly SQLite or something else later), and the Contract is the thing that must NOT change when that happens.
- Two Transports are planned from day one (CLI now, MCP server later) plus a third consumer (a community TUI) that binds through one of the two. All three must agree on one wire format without needing to coordinate release cadence with each other.
- The default schema pack has to reproduce today's real KB with zero data loss or renaming, which means the domain model has to be expressive enough for the actual existing shapes (product vs. project distinction, empty-string suppress sentinel in resolution maps, reserved keys like `_org`) before the schema pack is written.

This change produces two durable specs and no code: `domain-model` (the vocabulary) and `kb-contract` (the wire format). Everything downstream — the engine's internal types, the CLI's command surface, the MCP server's read-only ops — implements against these two specs rather than against each other.

## Goals / Non-Goals

**Goals:**
- Fix the four core domain primitives (Engine, Contract, Transport, Collection/Profile) and the five supporting primitives (Resolution map, Ledger, Document store, Schema pack) with enough precision that two independent implementers (engine track, CLI track) would produce compatible code.
- Fix the Contract's envelope, error-code taxonomy, versioning/compatibility rules, write-atomicity guarantee, and query/search capability so the engine's public API surface is fully specified before implementation.
- Preserve, in the spec text itself, every real invariant already present in the existing hand-maintained KB (product≠project, suppress sentinel, reserved resolution-map keys) so the future schema pack has a spec-level obligation to reproduce them exactly.

**Non-Goals:**
- No implementation. `packages/engine`, `packages/cli`, `packages/mcp-server` stay empty stubs after this change.
- No schema pack authoring (the actual field lists, section caps, and relationship names for people/products/projects/decisions). The domain-model spec only says the schema pack exists and what it must be able to express; concrete field definitions are a later deliverable.
- No transport wire encoding beyond "JSON envelope, semver-versioned." HTTP-vs-stdio-vs-subprocess plumbing details are CLI/MCP-server implementation concerns, not domain/contract concerns.
- No decision here about which storage engine replaces markdown+JSON (SQLite, etc.) — the whole point of the Contract is that this decision is deferred and non-breaking when made.

## Decisions

**Four core primitives, not one flat "record" type.** Engine/Contract/Transport/Collection-Profile map cleanly onto the existing architecture doc (README's Engine/Contract/CLI/MCP breakdown) and onto a real question every future PR will ask: "does this belong in the engine (owns invariants), the contract (wire shape), or a transport (process boundary, no logic)?" A flatter model (e.g., just "records" and "clients") would leave that question unanswered and invite business logic leaking into transports — which the existing README already calls out as a failure mode to avoid ("Transports contain no business logic").

**Collection/Profile as data-driven, not a closed enum of hardcoded types.** The real KB already has four-plus record kinds (people, products, projects, decisions) and issue #1 anticipates more. Hardcoding a `Person | Product | Project` union in the engine would mean every new collection is an engine code change. A schema pack that's data, not code, keeps the engine generic and testable against a synthetic fixture pack independent of the real KB's specific fields — while the domain-model spec still requires the *default* pack to reproduce the real KB exactly, so genericity doesn't come at the cost of fidelity.

**Resolution map as its own primitive, not a field on Profile.** Today's KB already has multiple independent resolution maps (names, projects, product-labels, github-repos) with a shared shape: variant → canonical, some reserved keys, and an empty-string sentinel meaning "known noise, suppress it, don't report as unresolved." Modeling this once as a primitive (rather than ad hoc per-collection alias fields) means the Contract's query operation can do alias-aware resolution generically across any collection that has one, and the engine can enforce the suppress-sentinel semantics in one place instead of once per map.

**Ledger as explicitly ephemeral, outside the durable KB.** The real KB already has runtime JSONL-ish scratch files (e.g., append-only entry logs) that are latest-write-wins by identity key and are not meant to be part of the reviewable, durable knowledge base. Calling this out as a named primitive with an explicit "ephemeral, outside the durable KB" boundary prevents future code from accidentally treating ledger entries as durable Profile data or vice versa.

**Document store as a fourth primitive alongside Profile, not a special case of Profile.** Long-form documents (openspec specs/changes, journal entries, decision logs) don't have the typed-field + relationship shape of a Profile — they're namespaced free text with a kind and optional structured provenance. Forcing them into the Profile shape would mean giving every Profile an unused freeform-body field or giving every document fake typed fields. Keeping them as a distinct primitive keeps both shapes honest.

**Response envelope: always `contract_version` + `ok` + (`data` xor `error`) + always-present `warnings[]`.** A discriminated-union envelope (`ok` boolean gates which of `data`/`error` is present) is a well-worn, easy-to-typecheck shape for a versioned JSON contract, and the always-present `warnings[]` array gives the deprecation mechanism (see next decision) a home without needing a schema-breaking field addition later.

**Error codes as a fixed, namespaced enum (`validation.*`, `not_found.*`, `conflict.*`, `contract.*`, `io.*`) with `path` (JSON Pointer) and `retryable` (boolean).** A closed set of prefixes lets clients branch on error *category* (is this my fault, a missing thing, a race, a version mismatch, or a transient storage problem?) without parsing message strings. JSON Pointer for `path` was chosen over a custom dotted-path format because it's a standard (RFC 6901), already unambiguous about array indices and escaping, and needs no bespoke parser on the client side.

**Contract versioning: independent semver from package versions, deprecation via `warnings[]` for one full minor cycle before a major removes.** Package versions (npm semver for `@kb/engine`, `@kb/cli`, etc.) track implementation churn; Contract semver tracks wire-compatibility. Decoupling them means the engine can ship a patch release with zero contract changes, or bump the contract's minor version for a new op without touching CLI package version at all. The one-full-minor-cycle deprecation window is a deliberately simple, unambiguous policy (no per-field custom sunset dates to track).

**Writes are atomic and fully invariant-checked before commit, across every denormalized copy.** Because Profiles have bidirectional relationships and Resolution maps have suppress/alias state, a naive per-field write could leave the store in a state where person A links to project B but B doesn't link back to A, or an alias exists in one map copy but not another. Requiring the engine to validate the *entire resulting state* before committing (not just the touched field) and write all denormalized copies atomically is the only way to guarantee "no transport can produce an inconsistent store" (already a stated invariant in the domain model).

**`query` is one operation covering full-text, field filters, relationship traversal, and alias resolution — not four separate ops.** The existing KB's main day-to-day usage pattern is "grep for a name/term and see everything related to it," which naturally spans substring matching, field filtering, and relationship-following in a single mental query. A combinable single op (AND-combined predicates) preserves that grep-like power (a design principle already stated in the README: "Going opaque must not lose grep-like search power") without forcing four separate round-trips that the caller then has to intersect themselves.

**CLI transport: JSON-only on stdout when not a TTY; stderr reserved for diagnostics; pretty-printing opt-in only when stdout is a TTY.** This is the standard Unix convention for tool output meant to be both human-usable and script/agent-pipeable (cf. `git`, `kubectl`, `gh`), and it directly serves the stated use case of the CLI being "used directly from the shell and by AI coding agents as a cheap, opaque subprocess call" (README) — an agent piping CLI output must never have to strip log lines out of stdout to parse JSON.

## Risks / Trade-offs

- **[Risk] A single generic `query` op could become a kitchen-sink API that's hard to implement efficiently.** → Mitigation: the spec fixes the required predicate types (text, field filter, `related_to`, alias resolution) and requires they combine with AND; it does not require boolean OR/NOT combinators or arbitrary predicate nesting in v0, keeping the surface bounded.
- **[Risk] Data-driven schema packs are more flexible but harder to statically type than a hardcoded union.** → Mitigation: out of scope for this change (schema pack contents are a later deliverable), but the domain-model spec explicitly requires the default pack to be validated against a fixture KB matching the real KB's layout, giving the future engine implementation a concrete acceptance test rather than relying on type-level guarantees alone.
- **[Risk] Decoupling Contract semver from package semver adds a second version number for consumers to track.** → Mitigation: the Contract exposes `kb contract version` for introspection and the envelope carries `contract_version` on every response, so no consumer needs to cross-reference package changelogs to know what contract they're speaking.
- **[Risk] Writing the domain-model and kb-contract specs before any implementation means they could be wrong in ways only implementation surfaces.** → Mitigation: expected and acceptable for Deliverable 0 — issue #1's later deliverables (engine, CLI) are the implementation that will pressure-test these specs; OpenSpec's delta-spec mechanism means future corrections are tracked as MODIFIED requirements against a clear baseline rather than silent drift.

## Migration Plan

Not applicable — this change adds new specs to a repo with no prior specs and no implementation. There is no existing behavior to migrate away from at the spec level. (The eventual markdown+JSON → opaque-format storage migration this spec anticorrelates is itself out of scope for this change; see Non-Goals.)

## Open Questions

- Whether the `query` op's AND-only combinator is sufficient long-term, or whether a future minor version needs OR/NOT — deferred until a real use case demands it (avoids speculative API surface).
- Whether non-CLI Transports (e.g. the future MCP server) need an equivalent to `--min-contract` version negotiation, and what that looks like outside a CLI flag — deferred to the MCP server deliverable; this change only fixes the CLI's negotiation surface and the resulting `contract.unsupported_version` error code.
