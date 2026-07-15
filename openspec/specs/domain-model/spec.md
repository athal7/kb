# domain-model Specification

## Purpose
Defines the vocabulary — Engine, Contract, Transport, Collection, Profile, Resolution map, Ledger, Document store, Schema pack — that every KB spec and implementation track is written against.

## Requirements
### Requirement: Term — Engine
The Engine SHALL be the deterministic library that owns every KB invariant and the on-disk format. No other component SHALL read or write storage directly.

#### Scenario: Engine owns invariants
- **WHEN** any consumer changes a record that has a bidirectional relationship (e.g. person↔project) or an alias
- **THEN** the Engine — not the consumer — updates both sides and the resolution map, so no transport can produce an inconsistent store

### Requirement: Term — Contract
The Contract SHALL be the single typed, versioned JSON request/response interface. It SHALL be the only public surface; the disk format is private and may change without a Contract change.

#### Scenario: Storage format is opaque
- **WHEN** the on-disk format migrates (e.g. markdown+JSON → SQLite)
- **THEN** the Contract version does not change and every consumer keeps working unmodified

### Requirement: Term — Transport
A Transport SHALL be a process boundary that carries the Contract. The CLI is the primary Transport; the MCP server is a secondary, read-only Transport. Transports SHALL contain no business logic.

#### Scenario: Transports are interchangeable for reads
- **WHEN** a read/query/resolve op is issued over the CLI or over MCP
- **THEN** both delegate to the same Engine call and return the same Contract envelope

### Requirement: Term — Collection
A Collection SHALL be a named set of Profile records sharing a schema (e.g. people, products, projects). Collections SHALL be configuration, not hardcoded types.

#### Scenario: Adding a Collection needs no engine code
- **WHEN** a new Collection is defined in the schema pack
- **THEN** the Engine serves it through the same generic Profile ops as existing collections

### Requirement: Term — Profile
A Profile SHALL be a structured record: typed fields + ordered freeform dated Sections + typed Relationships to other Profiles. Person/product/project are Profiles.

#### Scenario: Relationship edits stay bidirectional
- **WHEN** a Relationship is added to one Profile
- **THEN** the Engine writes the inverse Relationship on the target Profile automatically

### Requirement: Term — Resolution map
A Resolution map SHALL be a flat variant→canonical lookup with optional reserved keys and a suppress sentinel (empty-canonical = "noise, not real"). names/projects/product-labels/github-repos maps are instances.

#### Scenario: Suppress sentinel
- **WHEN** a variant resolves to the empty canonical value
- **THEN** the Engine reports it as suppressed rather than as an unresolved miss

### Requirement: Term — Ledger
A Ledger SHALL be an append-only stream of JSON entries where the latest entry per identity key is the current state. Ledgers SHALL be ephemeral local runtime state, outside the durable KB.

#### Scenario: Latest-wins projection
- **WHEN** multiple entries share an identity key
- **THEN** the Engine returns only the last-written entry as that key's state

### Requirement: Term — Document store
A Document store SHALL be a set of long-form documents namespaced by an external key (e.g. per-repo), holding multiple document kinds (standing vs dated-archived) plus optional structured provenance sidecars. The openspec store, journal, and decisions logs are instances.

#### Scenario: Namespaced retrieval with provenance
- **WHEN** a document is fetched from a namespace
- **THEN** the Engine returns its body, kind, and any provenance sidecar together

### Requirement: Term — Schema pack
A Schema pack SHALL be the data-driven definition mapping the four primitives to concrete KB shapes. The engine SHALL ship a default pack encoding today's KB; the pack is data, not a public extension API in v0.

#### Scenario: Default pack reproduces today's KB
- **WHEN** the engine loads the default schema pack against a fixture KB matching the real personal KB's layout
- **THEN** every file kind (people/products/projects/decisions/journal/name-maps/openspec docs) is readable and writable through the Contract with no data migration required
- **AND** the product-vs-project distinction, the empty-string suppress sentinel, and any reserved keys (e.g. `_org`) in resolution maps are preserved exactly

