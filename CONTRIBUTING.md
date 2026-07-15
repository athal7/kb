# Contributing

This is a cooperative, public tool with no deadline. Contributions welcome.

- Open an issue before starting a large change.
- Contract changes (the JSON read/write schema) require a design doc/spec first — every consumer binds to the contract, so changes there need more scrutiny than internal ones.
- Keep the engine free of transport-specific logic. The CLI and MCP server are thin adapters over the engine, not places to put new invariants.
- Run `bun install`, then whatever workspace scripts exist, once tooling lands.
