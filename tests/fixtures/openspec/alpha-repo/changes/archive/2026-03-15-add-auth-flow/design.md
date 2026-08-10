# Add Authentication Flow

## Context
The application currently has no user authentication. We need to add a login flow.

## Decisions
- Use session-based auth rather than JWT for simplicity
- Store sessions in Redis for distributed support
