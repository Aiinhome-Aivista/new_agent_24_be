# Test Evidence — EVID-fbfc1456
_Generated 2026-08-12T12:23:57.769840+00:00_

## Story

- **ORD-101** — Apply promotional discount and checkout order

## Test Cases
- `TC-001` [positive] Positive — valid input authorizes — status: AWAITING_REVIEW
- `TC-002` [negative] Negative — expired card rejected — status: AWAITING_REVIEW
- `TC-003` [boundary] Boundary — amount at limit — status: AWAITING_REVIEW

## Execution Summary
- Runner: mock (MOCK) · Total 3 · Passed 2 · Failed 1

## Code Quality
- Analyzer: mock (MOCK) · Score 92.0 · PASS