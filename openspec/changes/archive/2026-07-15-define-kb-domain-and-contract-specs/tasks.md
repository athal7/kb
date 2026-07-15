## 1. Domain model spec

- [x] 1.1 Author `domain-model` delta spec: Engine, Contract, Transport, Collection, Profile, Resolution map, Ledger, Document store, Schema pack requirements, each with at least one scenario
- [x] 1.2 Add the product-vs-project distinction note so the generic Collection/Profile vocabulary doesn't blur that the default schema pack keeps them as separate concrete collections

## 2. Contract spec

- [x] 2.1 Author `kb-contract` delta spec: Response Envelope, Error Codes, Contract Versioning, Atomic Invariant-Checked Writes, Query and Search, CLI Transport Contract requirements, each with at least one scenario

## 3. Validate and land

- [x] 3.1 Run `openspec validate` against the change and fix any reported errors
- [x] 3.2 Archive the change so the deltas merge into `openspec/specs/domain-model/spec.md` and `openspec/specs/kb-contract/spec.md`
- [x] 3.3 Commit the resulting spec files on `docs/kb-domain-and-contract-spec`
