# Test Evidence — EVID-ed5fecb0
_Generated 2026-08-19T13:12:41.873039+00:00_

## Story

- **TEST-2-101** — Sprint Story 2 — JWT Authentication and Security

## Test Cases
- `TC-001` [positive] Positive — Register a new user with unique email and valid password; verify user is saved, password is hashed, and response excludes password. — status: AWAITING_REVIEW
- `TC-002` [positive] Positive — Login with valid credentials; verify system returns a valid JWT token. — status: AWAITING_REVIEW
- `TC-003` [positive] Positive — Access a protected CRUD API with a valid JWT in the Authorization header; verify successful response. — status: AWAITING_REVIEW
- `TC-004` [negative] Negative — Attempt to access a protected CRUD API without an Authorization header; verify 401 Unauthorized response. — status: AWAITING_REVIEW
- `TC-005` [negative] Negative — Attempt to access a protected CRUD API with an invalid or malformed JWT; verify 401 Unauthorized response. — status: AWAITING_REVIEW
- `TC-006` [negative] Negative — Attempt to access a protected CRUD API with an expired JWT; verify 401 Unauthorized response. — status: AWAITING_REVIEW
- `TC-007` [boundary] Boundary — Register a user with an email that already exists in the database; verify registration is rejected. — status: AWAITING_REVIEW
- `TC-008` [boundary] Boundary — Attempt to login with a correct email but incorrect password; verify authentication failure. — status: AWAITING_REVIEW
- `TC-009` [validation] Validation — Verify that the returned user information object does not contain the hashed password field. — status: AWAITING_REVIEW
- `TC-010` [error] Error — Simulate a database connection failure during user registration; verify system handles exception gracefully. — status: AWAITING_REVIEW

## Execution Summary
- Runner: mock (MOCK) · Total 3 · Passed 2 · Failed 1

## Code Quality
- Analyzer: mock (MOCK) · Score 92.0 · PASS