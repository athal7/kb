# data-model Specification

## Purpose
Defines the core data model for the application.

## Requirements
### Requirement: Data models SHALL use ORM
All data models SHALL use the configured ORM for persistence.

#### Scenario: Model creation
- **WHEN** a new record is created
- **THEN** it is persisted through the ORM layer
