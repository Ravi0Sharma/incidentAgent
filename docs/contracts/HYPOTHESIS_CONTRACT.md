# Hypothesis and grounding contract

The deterministic layer produces ranked hypothesis candidates. It does not
produce a verified root cause.

## Observation before hypothesis

A catalog match first becomes `observed-signal/v1`. The record preserves its
evidence, signal family, entity scope, burst summary and typed impact links.
Recovery or success stays separate from adverse impact. A failure signal with
no compatible impact remains visible as observation-only.

Multiple competing failure categories, materially tied candidates or
contradictory evidence force abstention rather than an arbitrary winner.

## Candidate boundary

Every deterministic candidate is explicitly unverified:

```text
claim_type: hypothesis_candidate
causal_status: requires_verification
root_cause_status: not_established
```

Detection rules, timing and a preceding same-service deployment can raise a
candidate's investigation priority. They cannot establish causality by
themselves.

Each candidate includes:

- stable ID, rank, title and category;
- qualitative, uncalibrated confidence;
- supporting and contradicting evidence;
- assumptions and evidence gaps;
- observed signals and typed impact links; and
- the next safe verification step.

## Model boundary

Model interpretation must return structured JSON. Every rendered hypothesis
must match a deterministic candidate rank and cite resolvable evidence IDs.
Cause, mechanism and impact are separate typed claims.

The independent grounding pass:

- rejects unknown or candidate-incompatible evidence IDs;
- checks evidence roles for cause, mechanism, impact and contradiction;
- prevents outcome, recovery or success from proving adverse impact;
- prevents correlation from becoming an observed root cause;
- requires a validated cross-event link before rendering a mechanism;
- caps confidence when a source failed or evidence was truncated;
- permits only read-only next steps unless a mutation is clearly marked as a
  proposal requiring approval; and
- accepts zero hypotheses through explicit abstention.

Free-form titles, summaries and blast-radius wording are not trusted as facts.
Review Markdown is rendered from the validated structure.

## Abstention

The result is `No supported root cause yet` when:

- no candidate has compatible support;
- required evidence is missing, stale or malformed;
- leading candidates are materially tied;
- supporting and contradicting evidence conflict; or
- provider/model output fails its contract.

An abstention retains the incident window, available evidence, gaps and the
next smallest safe collection step. It never claims remediation occurred.

## Verification

The contract is covered by:

- `tests/test_hypothesis_contract.py`;
- `tests/test_claim_grounding.py`;
- `tests/test_signal_retention.py`;
- `tests/test_adversarial_boundaries.py`; and
- the label-last checks in [EVALUATION.md](../EVALUATION.md).

Numeric model confidence remains intentionally uncalibrated and is never proof
of causality.
