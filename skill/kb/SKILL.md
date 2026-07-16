# KB Agent Skill

This skill allows agents and third-party tools to interact with and query the KB engine via a structured, versioned, and typed Contract over the CLI.

## Installation

This skill can be installed via:
```bash
gh skill install athal7/kb kb
```

---

## CLI Reference & Examples

The CLI tool `kb` provides a clean, machine-parseable JSON interface on `stdout` by default. All logs, warnings, and diagnostics are sent to `stderr`.

### Envelope Structure & Command Outputs

The command-line output formats vary depending on the subcommand invoked:

1. **Query and search operations (`kb query`):**
   Always wrap their data payload inside the standard JSON Contract Response envelope:
   ```json
   {
     "contract_version": "0.1.0",
     "ok": true,
     "warnings": [],
     "data": { ... }
   }
   ```

2. **Contract version introspection (`kb contract version`):**
   Returns a clean, bare version string (e.g. `0.1.0`) on `stdout`.

3. **Contract schema introspection (`kb contract schema`):**
   Returns the raw contract JSON Schema as a standard JSON object.

On error, the envelope is:
```json
{
  "contract_version": "0.1.0",
  "ok": false,
  "warnings": [],
  "error": {
    "code": "validation.section_cap",
    "message": "Section 'Current' has exceeded the cap of 5 items.",
    "path": "/sections",
    "retryable": false
  }
}
```

### Introspection Verbs

- **Get Contract Version:**
  ```bash
  kb contract version
  ```
- **Get JSON Schema:**
  ```bash
  kb contract schema
  ```

### Query Verb (`kb query`)

The `kb query` subcommand performs advanced searching across profiles and documents:

- **Full-Text search across sections and frontmatter:**
  ```bash
  kb query -t "gRPC"
  ```
- **Field filtering (supports `=`, `!=`, `>`, `<`, `>=`, `<=`, `contains`):**
  ```bash
  kb query -f "status=active"
  ```
- **Collection scoping (e.g., search only in `people` or `journal`):**
  ```bash
  kb query -c people -c journal
  ```
- **Relationship traversal (e.g., find projects related to a person):**
  ```bash
  kb query -r "people/andrew-thal" --relationship projects
  ```

---

## KB Domain Behavioral Guidance

When updating or reading the KB, you must adhere to the following domain concepts and vocabularies:

### 1. Primitives and Collections
- **people:** Structured profiles for team members containing fields like `email`, `team`, `title`, `slack_id`, and `aliases`.
- **projects:** Structured profiles for active projects, containing `status`, `github` repository, `linear` link, and `aliases`.
- **products:** Structured profiles for products mapping to projects. Products have `status`, `repos`, and a `linear` label.
- **decisions:** Long-form markdown documents tracking architecture or organizational decisions.
- **journal:** Dated logs tracking daily/weekly notes and updates.

### 2. Resolution Maps and Alias-Aware Search
- Variant names (like nicknames, initials, or old product handles) are mapped to canonical keys in resolution map files (`names.json`, `projects.json`, `product-labels.json`).
- If a query uses an alias like `athal`, the search resolves it to the canonical ref `people/andrew-thal` and includes that record, even if the literal text `athal` is not in the markdown file.
- Suppress sentinel: empty canonical strings (`""`) in mapping files indicate that the entry should be ignored/suppressed rather than treated as a missing lookup.

### 3. Invariants and Section Caps
- **Current Section Cap:** Any section with the heading `Current` (case-insensitive) is limited to at most **5 bullet items** (lines starting with `-` or `*`). Writes exceeding this cap will be rejected with a validation error.
- **Bidirectional Symmetry:** When adding a project relationship to a person, the inverse relationship is automatically synced on the project profile, and vice versa.

---

## Collector Convention

Third-party scripts, watchers, or agents can easily write facts and documents into the KB using **Collectors**.

### Pattern
1. Create a lightweight external script (e.g., a GitHub Action or a cron job) that polls or receives events from external sources (such. as Slack, GitHub issues, Linear tasks, or email).
2. Extract the relevant metadata, dated bullet, or profile update.
3. Call `kb query` to check if a relevant profile or document exists.
4. Call the KB Engine's write mechanics (or a future write-back command) to append the extracted information as a new section bullet, sync relationships, or register new aliases.
5. All writes are atomic and guaranteed to be validated before being committed to disk.
