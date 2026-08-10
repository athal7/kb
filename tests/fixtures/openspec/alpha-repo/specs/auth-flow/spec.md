# auth-flow Specification

## Purpose
Defines the authentication flow requirements for the application.

## Requirements
### Requirement: User login SHALL require credentials
Users SHALL authenticate with a username and password.

#### Scenario: Successful login
- **WHEN** a user provides valid credentials
- **THEN** a session is created and the user is redirected
