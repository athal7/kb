"""The Contract's own semver, independent of the `kb` package version.

Per kb-contract/spec.md's Contract Versioning requirement: additive changes (new op,
new optional field, new schema-pack collection) bump the minor version; breaking
changes (removed/renamed field, changed op semantics, changed error-code meaning)
bump the major version.
"""

from __future__ import annotations

CONTRACT_VERSION = "0.1.0"
