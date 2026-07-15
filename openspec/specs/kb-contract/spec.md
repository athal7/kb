# kb-contract Specification

## Purpose
Defines the versioned JSON request/response Contract every Transport (CLI, MCP server) speaks: the response envelope, error-code taxonomy, versioning/compatibility rules, atomic write guarantees, the query/search operation, and the CLI transport's stdout/stderr behavior.

## Requirements
### Requirement: Response Envelope
Every Contract response SHALL be one JSON object with `contract_version`, `ok`, and either `data` (on success) or `error` (on failure), plus an always-present `warnings` array (empty when there are none).

#### Scenario: Successful response shape
- **WHEN** an operation succeeds
- **THEN** the response has `ok: true` and a `data` field containing the operation's payload

#### Scenario: Error response shape
- **WHEN** an operation fails
- **THEN** the response has `ok: false` and an `error` field with `code`, `message`, `path`, and `retryable`

### Requirement: Error Codes
Errors SHALL carry a stable, namespaced code from a fixed enum of prefixes: `validation.*`, `not_found.*`, `conflict.*`, `contract.*`, `io.*`. The `path` field SHALL be a JSON Pointer into the request payload identifying the offending field. The `retryable` boolean distinguishes transient failures from deterministic ones.

#### Scenario: Validation failure
- **WHEN** a write violates a schema or invariant (e.g. section cap exceeded)
- **THEN** the engine returns a `validation.*` code with `retryable: false` and a `path` pointing at the offending field

#### Scenario: IO failure
- **WHEN** a storage-layer operation fails transiently (e.g. a lock contention or disk error)
- **THEN** the engine returns an `io.*` code with `retryable: true`

### Requirement: Contract Versioning
The Contract SHALL carry its own semver, independent of package versions. Additive changes (new op, new optional field, new collection in the schema pack) SHALL bump the minor version. Breaking changes (removed/renamed field, changed op semantics, changed error-code meaning) SHALL bump the major version.

#### Scenario: Forward compatibility on responses
- **WHEN** a client receives a response with fields it does not recognize
- **THEN** it must ignore them without erroring

#### Scenario: Forward compatibility on requests
- **WHEN** the engine receives a request with fields it does not recognize
- **THEN** it accepts and ignores them rather than rejecting the request

#### Scenario: Deprecation window
- **WHEN** a field or op is deprecated
- **THEN** the engine emits a `warnings[]` entry with code `deprecation.*` for at least one full minor version cycle before a major version removes it

#### Scenario: Version negotiation
- **WHEN** a client requests a `--min-contract` version the engine cannot satisfy
- **THEN** the engine returns error code `contract.unsupported_version` instead of silently changing behavior

### Requirement: Atomic, Invariant-Checked Writes
Every write SHALL validate the full resulting state — relationship symmetry, alias/resolution-map sync, section caps — before committing, and SHALL never partially write.

#### Scenario: Invariant violation blocks the write
- **WHEN** a write would leave the store in a state that violates an invariant
- **THEN** the engine rejects the entire write with a `validation.*` or `conflict.*` error and the on-disk state is unchanged

#### Scenario: Successful write updates all denormalized sides
- **WHEN** a write adds a bidirectional relationship or a resolution-map alias
- **THEN** the engine updates every denormalized copy (both Profile sides, the map, and any mirrored alias list) in the same atomic operation

### Requirement: Query and Search
The Contract SHALL expose a `query` operation that at minimum supports: substring/full-text matching across record bodies, section content, and frontmatter-style field values; structured field-level filter predicates (`field`, `op`, `value`); scoping to one, several, or all collections/primitives (profiles and documents both reachable); relationship traversal (e.g. all Profiles related to a given ref via a named relationship) resolved through the engine's relationship index rather than string matching; and alias-aware term resolution via the Resolution map primitive so a name variant matches its canonical record.

#### Scenario: Substring match across sections
- **WHEN** a query text matches a substring inside any section or frontmatter field of a Profile
- **THEN** that Profile appears in the results with `matched_in` identifying which field/section matched

#### Scenario: Field filter predicate
- **WHEN** a query includes a filter like `status = active`
- **THEN** only Profiles whose `status` field equals `active` are returned

#### Scenario: Relationship traversal
- **WHEN** a query specifies `related_to` with a ref and a relationship name
- **THEN** the engine returns only Profiles reachable via that named relationship from the given ref, using the relationship index, not text matching

#### Scenario: Alias-aware term resolution
- **WHEN** a query text matches a known variant in a Resolution map
- **THEN** Profiles under the canonical name are included in the results even though the literal query text does not appear verbatim in the record

#### Scenario: Result shape
- **WHEN** a query returns hits
- **THEN** each hit includes a stable opaque `ref` (never a file path), the owning `collection`, a `snippet`, `matched_in`, and any directly related refs
- **AND** the response also reports `total` and whether results were `truncated` by a limit

#### Scenario: Multiple predicates combine with AND
- **WHEN** a query specifies text, filters, and `related_to` together
- **THEN** only records satisfying all of them are returned

### Requirement: CLI Transport Contract
The CLI transport SHALL emit the Contract envelope as JSON on stdout by default, reserving stderr for diagnostics/logs, so stdout is always a cleanly parseable envelope for scripts and agents.

#### Scenario: Default machine-readable output
- **WHEN** the CLI is invoked with stdout not attached to a TTY (e.g. piped or captured by a subprocess caller)
- **THEN** it prints only the JSON envelope to stdout, with no other text mixed in

#### Scenario: Human-friendly output opt-in
- **WHEN** the CLI is invoked with stdout attached to a TTY
- **THEN** it may render a human-readable pretty form, but the underlying data is unchanged, and diagnostics/logs still never appear on stdout

#### Scenario: Contract introspection
- **WHEN** `kb contract version` or `kb contract schema` is invoked
- **THEN** the CLI returns the current contract semver or its JSON Schema respectively

