# Test Evidence — EVID-3fac4c25
_Generated 2026-08-19T12:30:22.455893+00:00_

## Story

- **TEST-2-101** — Sprint Story 2 — JWT Authentication and Security

## Test Cases
- `TC-001` [positive] Positive — Register a new user with unique email and valid password, verify password is hashed and user is saved. — status: AWAITING_REVIEW
- `TC-002` [positive] Positive — Login with valid credentials and receive a JWT token. — status: AWAITING_REVIEW
- `TC-003` [positive] Positive — Access a protected CRUD API endpoint by providing a valid JWT in the Authorization header. — status: AWAITING_REVIEW
- `TC-004` [negative] Negative — Attempt to access a protected CRUD API without providing an Authorization header. — status: AWAITING_REVIEW
- `TC-005` [negative] Negative — Attempt to access a protected CRUD API with an invalid or malformed JWT. — status: AWAITING_REVIEW
- `TC-006` [negative] Negative — Attempt to register with an email address that already exists in the system. — status: AWAITING_REVIEW
- `TC-007` [boundary] Boundary — Attempt to access a protected CRUD API with an expired JWT token. — status: AWAITING_REVIEW
- `TC-008` [boundary] Boundary — Register a user with the minimum and maximum allowed password lengths (if defined by system policy). — status: AWAITING_REVIEW
- `TC-009` [validation] Validation — Verify that the user information returned after registration does not contain the password field. — status: AWAITING_REVIEW
- `TC-010` [error] Error — System fails to authenticate when the JWT signature does not match the server's secret key. — status: AWAITING_REVIEW

## Execution Summary
- Runner: mock (MOCK) · Total 3 · Passed 2 · Failed 1

## Code Quality
- Analyzer: mock (MOCK) · Score 92.0 · PASS