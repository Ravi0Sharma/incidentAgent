# Deferred Connection And Provider Failure Tests

These checks are intentionally parked while the active work remains focused on
data quality, candidate ranking and the review boundary.

## OpenAI/provider cases

- connection refused or DNS failure;
- connect/read timeout;
- HTTP 401/403 invalid or unauthorized key;
- HTTP 429 and retry classification;
- provider circuit open;
- empty response or response without usage metadata;
- request exceeding the remaining incident deadline.

## Expected contract when resumed

- the incident and deterministic evidence remain available;
- no provider error is represented as “no matching evidence”;
- no new causal claim is introduced by fallback behavior;
- review is marked degraded or abstained as appropriate;
- request ID, retry count, deadline state and available usage are retained;
- external publishing remains disabled.

These are not active gates for the current three-scenario review evaluation.
They should be reinstated before Shadow or hosted deployment.

## Observation 2026-07-28

The first live provider request in `scripts/evaluate_review_scenarios.py`
failed through the shared provider wrapper and opened the circuit; subsequent
semantic requests were therefore blocked as designed. The three selected data
scenarios still produced correct deterministic supported/abstained review
states. Root cause classification for the provider failure is deliberately
deferred under this file instead of blocking the current data evaluation.
