# api-contract Specification

## Purpose
Defines the API contract for beta-project services.

## Requirements
### Requirement: API responses SHALL include status code
All API responses SHALL include an HTTP status code.

#### Scenario: Successful response
- **WHEN** a request succeeds
- **THEN** the response includes a 200 status code
