# Incident Agent - Hypothesis Candidate Contract

**Current deterministic candidate schema:** `deterministic-candidate/v1`  
**Current observed signal schema:** `observed-signal/v1`  
**Current impact assessment schema:** `impact-assessment/v1`  
**Current signal-impact schema:** `signal-impact-link/v2`  
**Current pre-review model schema:** `model-interpretation/v1`  
**Current grounding schema:** `claim-grounding/v1`

The deterministic scoring layer produces **hypothesis candidates**. It does not
produce a verified root cause. Every candidate carries a rank, trigger, cause
label, uncalibrated qualitative confidence, supporting and contradicting
evidence, assumptions, gaps, and the next verification step.

## Observation Before Hypothesis

A direct catalog match first becomes `observed-signal/v1`, not a cause. The
record preserves its event ID, signal family/status, minimized workload and
execution scope, `event-burst/v1` summary, and any `signal-impact-link/v2`
records plus a typed `impact-assessment/v1`.

Impact links can show an explicit operation effect, a shared-entity adverse
lifecycle event, or later recovery/success. Every link remains
`causal_status: not_established`. A recovered signal without linked adverse
impact remains visible as observation-only. Multiple observed failure
categories force abstention even when one would otherwise rank first.

`impact-assessment/v1` keeps fault, impact, adverse outcome, general outcome,
recovery and contradicting event IDs in separate roles. Entity compatibility
is `exact`, `workload_only`, `unknown` or `mismatch`; time relation is
`before`, `during`, `after` or `unknown`. A success on the same workload may
contradict incident impact, but an adverse lifecycle event from a conflicting
execution cannot establish impact for the observed fault.

## Causal Guardrail

All current deterministic candidates have:

- `claim_type: hypothesis_candidate`;
- `causal_status: requires_verification`;
- `root_cause_status: not_established`;
- `mechanism: null`; and
- `impact_link: null`.

This makes the limit explicit: detection rules, timing, and a preceding
same-service deploy can increase investigation priority, but cannot establish a
root cause by themselves. The deploy correlation only includes a matching
service deployment that occurred in the 15-minute window before the first error.

## Current Candidate Fields

| Field group | Fields |
| --- | --- |
| Identity and ranking | `candidate_schema_version`, `id`, `rank`, `title`, `cause`, `category` |
| Claim boundary | `claim_type`, `trigger`, `causal_status`, `root_cause_status`, `mechanism`, `impact_link` |
| Confidence | `score`, `confidence`, `confidence_label`, `confidence_calibration`, `reasons`, `assumptions` |
| Evidence | `event_ids`, `evidence`, `supporting_evidence`, `weaknesses`, `contradicting_evidence`, `gaps`, `symptoms`, `contributing_factors` |
| Observation context | `observation_ids`, `impact_links`, `impact_event_ids`, `adverse_outcome_event_ids`, `outcome_event_ids`, `recovery_event_ids`, `successful_completion_event_ids`, `contradicting_event_ids` for signal-derived candidates |
| Next action | `verification`, `next_verification`, `recovery_actions` |

## Pre-review Model And Grounding Contract

Interpretation now accepts JSON only. Each model hypothesis must match a
deterministic rank and cite resolvable evidence IDs. Cause, mechanism and impact
are separate typed claims. The independent grounding pass:

- rejects unknown or candidate-incompatible evidence IDs;
- resolves known IDs into explicit cause, mechanism, impact, contradiction,
  outcome, recovery and successful-completion roles;
- prevents general outcomes, recovery or successful completion from proving an
  adverse-impact claim;
- allows impact claims to cite only explicit impact or adverse-outcome IDs,
  while preserving general outcome, recovery, success and contradiction as
  separate context without strengthening the cause claim;
- prevents correlation from becoming an observed root cause;
- requires a validated cross-event semantic link before rendering a mechanism;
- caps confidence when a source failed or log evidence is truncated;
- accepts read-only next steps through a positive verb policy, requires unknown
  or mutating steps to be explicit proposals with approval, and removes claims
  that an action was already executed without action evidence; and
- permits zero hypotheses through an explicit abstention.

Review Markdown is a rendering of this validated structure. The model's free
TL;DR, title and blast-radius wording are not trusted as factual output.

## Remaining Work

RCA and postmortem still use their existing later-stage contracts and must
eventually consume the exact approved typed hypothesis/revision. Numeric
probabilities remain intentionally uncalibrated, and broader cross-source
contradiction/type-compatibility evaluation remains open.

## Test Mapping

- `A05-T02` subset: `tests/test_hypothesis_contract.py` validates candidate
  schema and scoring boundaries.
- `A05-T03` subset: `tests/test_hypothesis_contract.py` validates temporal and
  same-service deploy correlation.
- `A05-T04` subset: `tests/test_hypothesis_contract.py` validates the valid
  insufficient-evidence result before model reasoning.
- `A05-T07` subset: `tests/test_hypothesis_contract.py` validates a factual
  log-versus-metric contradiction. Final hypotheses, grounding, revision and
  calibrated probabilities remain open.
- The degraded-output tests prove that model bypass/provider fallback renders
  only actual deterministic candidates and gaps, does not force three
  hypotheses or numeric probabilities, and cannot add causal RCA/postmortem
  claims.
- The approved-context test proves that raw incident volume remains visible as
  an aggregate count while downstream RCA/postmortem detail is bounded.
- `tests/test_claim_grounding.py` covers typed rendering, hallucinated IDs,
  role-incompatible known IDs, adverse-impact versus successful-completion
  separation, causal downgrades, mechanism links, confidence caps, unsafe
  actions and non-JSON abstention.
- `tests/test_signal_retention.py` covers observation-only signals, minimized
  entity links, recovery context, competing-category abstention and collapsed
  burst summaries.
