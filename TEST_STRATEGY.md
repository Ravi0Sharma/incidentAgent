# Incident Agent - Test Strategy And Verification Plan

> This document defines how we prove that areas 1-15 in
> `PRODUCTION_READINESS.md` work. The readiness checklist says **what** must be
> true; this document says **how** we test it and what evidence is required.

## The Core Rule

A feature is not done because the happy path worked once. It is done when:

1. its contract and invariants are explicit;
2. positive, negative, boundary, and failure tests pass;
3. persistence/restart/concurrency behavior is tested where relevant;
4. security and data-leak behavior is tested where relevant;
5. telemetry proves the behavior in a production-like environment;
6. quality, latency, and cost stay inside the approved limits; and
7. the exact test result is attached to the release evidence.

Every readiness criterion must link to one or more test IDs from this plan or a
more specific test introduced with the implementation.

## Test Oracles: How We Know The Result Is Correct

Different parts of the agent need different kinds of truth. Use the strongest
available oracle rather than asking another LLM whether the output “looks good.”

| Oracle | Used for | Passing rule |
| --- | --- | --- |
| Exact output | IDs, state transitions, redaction, timestamps, budgets, API errors | Actual value exactly matches the specified value |
| Schema/invariant | Evidence, hypotheses, reviews, audit, structured model output | Every required field and invariant holds; forbidden states never occur |
| Source reconciliation | Logs, metrics, deploys, traces | Stored result reconciles with a controlled backend response and provenance |
| Labeled incident truth | Ranking, causality, abstention, citations | Meets agreed precision/recall/calibration thresholds on the versioned gold set |
| Human adjudication | Usefulness, clarity, postmortem quality | Blinded SRE review meets threshold with disagreements recorded/adjudicated |
| Operational SLO | Reliability, latency, cost, recovery | Measured telemetry meets the ratified SLO over the defined window |
| Security assertion | Auth, isolation, leakage, injection, unsafe output | Forbidden access/effect/leak occurs zero times in the security suite |

An LLM judge may be an additional signal, but it cannot be the only oracle for
security, citations, factual correctness, authorization, or external effects.

## Test Levels

| Level | Name | Runs | Purpose |
| --- | --- | --- | --- |
| L0 | Static validation | Every change | Format, types, schemas, links, config, dependency and secret checks |
| L1 | Unit/property | Every change | Pure functions, invariants, boundaries, redaction, scoring, state rules |
| L2 | Component/contract | Every change where practical | One service or connector against a controlled fake/ephemeral dependency |
| L3 | Integration | Every change/nightly | API, queue, database, workers, model adapter, object store, identity |
| L4 | End-to-end | Nightly and release | Alert to review to draft/publish using sandbox destinations |
| L5 | Non-functional | Scheduled and release | Security, load, soak, concurrency, crash, chaos, backup/restore |
| L6 | Shadow/human evaluation | Before pilot and continuously | Real read-only telemetry, labeled comparison, reviewer usefulness |

## Test Environments

| Environment | Data | External effects | Main tests |
| --- | --- | --- | --- |
| Local | Synthetic fixtures only | Disabled | L0-L2, deterministic stub |
| CI ephemeral | Generated/sanitized fixtures; disposable dependencies | Fake/sandbox only | L0-L4 subset |
| Integration | Production-like schemas and backend versions | Sandbox destinations | Full connector, queue, database, model-adapter tests |
| Staging | Sanitized replay plus synthetic failures | Sandbox destinations behind approval | E2E, security, load, crash, migration, rollback |
| Shadow | Approved production telemetry, read-only | Technically blocked | Quality, latency, cost, data safety, source coverage |
| Controlled pilot | Approved production telemetry | Explicitly approved drafts only | Human workflow and operational SLO verification |

No automated test may possess credentials capable of writing to real incident
channels, production GitHub projects, or production remediation systems.

## Test Data Plan

Maintain four distinct datasets:

1. **Small deterministic fixtures:** hand-written cases for fast exact tests.
2. **Generated/adversarial corpus:** malformed payloads, timestamp boundaries,
   secret/PII patterns, injection strings, large incidents, and concurrency.
3. **Sanitized incident replays:** production-shaped data with approval and no
   recoverable direct identifiers or credentials.
4. **Versioned gold set:** at least 100 representative incidents with incident
   window, impact, accepted evidence, accepted cause(s), alternatives,
   invalid causal shortcuts, expected abstention, and reviewer adjudication.

Each dataset needs a version, owner, provenance, security classification,
license/usage permission, retention rule, and change log. The evaluation report
must name the exact dataset version.

The local pre-review gate is documented in `PRE_REVIEW_EVALUATION.md`.
`scripts/evaluate_pre_review.py` exercises exact synthetic causal
counterexamples. `scripts/evaluate_public_logs.py` exercises parsing, timestamp,
sampling, and grouping robustness on allowlisted public logs. Public template
labels are not accepted as root-cause truth and cannot close the labelled
incident-gold-set requirement.

## Required Test Evidence

For each release, store a machine-readable test manifest in the CI artifact
system. It should contain:

- release commit and artifact digest;
- test ID and mapped readiness criterion IDs;
- environment and dependency versions;
- model/provider/prompt/rule/config versions;
- dataset version and random seed where applicable;
- start/end time and duration;
- pass/fail/skip plus reason;
- quality, latency, token, tool, and cost measurements;
- logs/traces/report links with sensitive content removed; and
- approver for manual, shadow, security, or recovery evidence.

Skipped P0 tests fail the release unless a named owner records a time-bounded
risk acceptance. Re-running only failed LLM samples until they pass is not
allowed; the full run and failure rate must be retained.

## Area 1 - Product Scope And Safety Contract

| Test ID | What we test | Method and environment | Pass condition |
| --- | --- | --- | --- |
| `A01-T01` | Supported-input matrix | Table-driven contract tests in CI for every supported and unsupported source/environment/version combination | Supported inputs enter the documented path; unsupported inputs return the documented error and never start analysis |
| `A01-T02` | Non-goal enforcement | E2E attempts to request remediation, arbitrary chat, raw-log export, and unreviewed publication | Every forbidden action is unavailable or denied with an audit event; zero external effect |
| `A01-T03` | Fail-open/fail-closed policy | Scenario matrix: missing source, model outage, auth outage, audit outage, publisher outage | Result matches policy exactly; auth/audit/publication fail closed and optional evidence becomes explicit degradation |
| `A01-T04` | Abstention policy | Gold cases with no evidence, stale evidence, contradictory evidence, false alerts, and unknown failure types | Agent abstains where labeled and returns gaps/next checks without inventing a root cause |
| `A01-T06` | Change-control gate | Submit a deliberately regressing prompt/rule/config in a test branch | CI blocks promotion, explains the failed gate, and the previous version remains deployable |

Evidence to close Area 1 for the POC: support matrix, policy scenario report,
abstention metrics, and change-gate demonstration. Formal SLO/ownership
governance is outside the current POC scope.

## Area 2 - Alert Intake And Incident Lifecycle

| Test ID | What we test | Method and environment | Pass condition |
| --- | --- | --- | --- |
| `A02-T01` | Versioned input schema | Positive/negative API contract suite for missing fields, wrong types, unknown versions, label limits, timestamps, and batch limits | Only valid documented payloads are accepted; each invalid class returns the specified 4xx response |
| `A02-T02` | Authentication and replay | Valid/invalid HMAC, changed body, expired timestamp, reused nonce, clock-boundary tests | Only the first valid in-window request succeeds; all failures are counted and audited without state mutation |
| `A02-T03` | Body/rate limits | Boundary payload sizes plus per-caller/global burst load | Limit-1 is accepted, limit+1 is rejected early, and one caller cannot starve another |
| `A02-T04` | Durable-before-ack | Kill API/worker/database at controlled points immediately after response | Every acknowledged event exists after restart and is processed exactly through idempotent at-least-once delivery |
| `A02-T05` | Exact duplicate handling | Send the identical signed event repeatedly and concurrently | One event record and one analysis effect; duplicate count/audit increases; no duplicate revision or publish |
| `A02-T06` | Incremental observations | Add a new log/metric/deploy alert to a pending and completed incident | Same incident gets a new evidence and analysis revision; old verified evidence remains addressable |
| `A02-T07` | Out-of-order and late events | Deliver receive order different from event time, including beyond normal delay | Timeline uses event time, audit preserves arrival order, and revision diff explains the late change |
| `A02-T08` | Lifecycle state machine | Model-based tests attempt every legal and illegal transition | All legal transitions succeed once; illegal/stale transitions fail without partial state |
| `A02-T09` | Resolved notification | Fire, update, resolve, duplicate resolve, and reopen scenarios | Resolution is idempotent and follows the documented analysis/review/postmortem policy |
| `A02-T10` | Concurrent writers/reviewers | Multiple workers and reviewers race on one incident revision | One version wins; stale writes receive conflict; no evidence/review is silently lost |
| `A02-T11` | Dead-letter and replay | Permanent invalid event and transient exhausted event | Redacted failure enters the correct queue; authorized replay succeeds once without duplicate effects |
| `A02-T12` | Reprocessing | Re-run stored evidence with same and newer code/model/prompt versions | Same version is reproducible within declared tolerance; new revision is linked; external effects remain disabled/idempotent |

Evidence to close Area 2: API contract report, state-machine/property report,
concurrency run, crash-point matrix, queue reconciliation, and persisted revision
examples.

## Area 3 - Telemetry And Change-Source Connectors

Run the same connector contract against Loki, Prometheus, deployment, trace,
and every later source. Mocks alone are not enough; at least one ephemeral or
sandbox instance of the real backend/version must pass.

| Test ID | What we test | Method and environment | Pass condition |
| --- | --- | --- | --- |
| `A03-T01` | Shared connector contract | Controlled backend responses for success, empty, forbidden, rate-limited, malformed, partial, stale, and unavailable | Each condition maps to the correct typed status; empty is never confused with failed |
| `A03-T02` | Time and filter correctness | Seed records just inside/outside windows and across services/environments | Only authorized matching records are returned; boundaries and UTC conversion are exact |
| `A03-T03` | Pagination and hard limits | Dataset larger than every page/sample/group limit | Counts/truncation are correct, memory remains bounded, and no hidden unlimited pagination occurs |
| `A03-T04` | Timeout/retry/circuit behavior | Delays, connection resets, 429 with retry hints, 5xx, cancellation | Bounded retries/jitter match config; circuit opens/recovers; deadline and cancellation are respected |
| `A03-T05` | Query provenance | Execute every query type and reconcile stored metadata with fake backend request logs | Backend/tenant/window/query fingerprint/result count/truncation/request ID are complete and sanitized |
| `A03-T06` | Least privilege | Attempt write/admin/cross-environment operations with production-equivalent connector roles | Read requirements succeed; forbidden operations and cross-scope reads fail and are audited |
| `A03-T07` | Deployment truth | Seed commit-only, failed, staging, and successful production deploy records | Only actual matching environment/service deployments are labeled as production deploy evidence |
| `A03-T08` | Trace lookup | Seed multi-service traces with missing spans, large traces, and unrelated tenant trace | Bounded graph is correct; missing data is explicit; unauthorized/unrelated spans never appear |
| `A03-T09` | Multi-backend routing | Services mapped to different tenants/backends plus malicious caller-provided URL | Correct configured backend is used; caller cannot redirect traffic or provide credentials |
| `A03-T10` | Freshness | Reachable backend with newest sample older than the incident | Source becomes `stale`/low quality rather than healthy-empty |

Evidence to close Area 3: one contract report per connector/backend version,
least-privilege proof, query reconciliation, and failure-injection traces.

## Area 4 - Evidence Reduction, Provenance, And Timeline

| Test ID | What we test | Method and environment | Pass condition |
| --- | --- | --- | --- |
| `A04-T01` | Canonical normalization | Golden records from every supported schema, aliases, missing/extra fields, and level variants | Canonical output exactly matches fixtures and preserves allowed source metadata |
| `A04-T02` | Recursive redaction | Secret/PII corpus in every nested field, annotation, URL, error, tool result, feedback, and label | Zero forbidden values appear in DB, checkpoint, prompt, trace, log, report, memory, or publisher payload |
| `A04-T03` | Grouping correctness | Duplicates, dynamic IDs/numbers, distinct errors, multiple services/pods/routes, and hash collisions | Equivalent events group; materially different events do not; totals reconcile with fetched data |
| `A04-T04` | High-volume rare-signal retention | Millions of generated common logs plus rare critical first/peak/last and cross-service events | State/context limits hold and all specified high-signal representatives remain in the evidence pack |
| `A04-T05` | Truncation and sampling honesty | Exact, approximate, failed-count, and truncated source responses | Every count carries correct scope/exactness; report never presents a sample count as full truth |
| `A04-T06` | Stable evidence identity | Reorder input, retry collection, append unrelated evidence, and supersede a record | Unchanged evidence keeps ID/hash; correction creates a linked new version; no silent overwrite |
| `A04-T07` | Timeline correctness | Timezones, DST, invalid/future times, equal timestamps, late arrival, and clock skew | UTC order, original time, arrival order, anchor, and quality flags match the specification |
| `A04-T08` | Citation resolution | Generate valid, missing, cross-incident, wrong-type, and superseded evidence references | Valid citations resolve; all invalid references are blocked or explicitly downgraded |
| `A04-T09` | Provenance integrity | Modify stored evidence/query metadata after collection in a controlled test | Integrity check detects change and prevents it from being treated as reviewed evidence |
| `A04-T10` | Untrusted-text boundary | Put policy/tool instructions in logs, annotations, commits, memory, and feedback | Instructions remain quoted data, cannot alter policy, and cannot trigger unapproved tool calls |
| `A04-T11` | Incremental recomputation | Append evidence affecting one service/window branch | Only dependent summaries revise; unchanged evidence and conclusions retain IDs/version links |
| `A04-T12` | Data-quality score | Controlled combinations of stale, missing, truncated, skewed, and misattributed sources | Score/reasons exactly match the defined formula and lower downstream confidence appropriately |

Evidence to close Area 4: golden fixture diff, property/fuzz report, leak scan,
large-volume benchmark, citation validator report, and revision lineage example.

## Area 5 - Deterministic Detection, Correlation, And Hypotheses

| Test ID | What we test | Method and environment | Pass condition |
| --- | --- | --- | --- |
| `A05-T01` | Rule behavior | Positive/negative/boundary fixtures for every rule and suppression | Each rule meets its precision/recall target; suppression never hides labeled causal evidence |
| `A05-T02` | Scoring invariants | Property tests vary order, duplicate evidence, counts, severity, and source quality | Input order/duplicates do not inflate rank; score stays bounded and reasons match contributing facts |
| `A05-T03` | Temporal causality guard | Deploy before/after symptom, unrelated service/env, and no mechanism | Post-symptom/unrelated deploy is never cause; proximity alone is labeled correlation/inference |
| `A05-T04` | Typed hypothesis contract | Missing/extra/invalid ranks, confidence, evidence, mechanism, gaps, and contradiction fields | Only schema-valid hypotheses enter review; exact invariant failures are reported |
| `A05-T05` | Grounding gate | Inject unsupported claim, unknown citation, wrong evidence type, and contradicted critical claim at all generation stages | Critical unsupported claim never reaches approval/publish; result is removed, downgraded, or revised |
| `A05-T06` | Abstention | Labeled insufficient/ambiguous/false-alert cases | Agent returns no supported root cause and useful next evidence request at the required rate |
| `A05-T07` | Contradiction handling | Controlled logs/metrics/deploys that disagree | Contradiction is visible, confidence decreases according to policy, and no source is silently ignored |
| `A05-T08` | Incremental re-ranking | Add supporting, contradicting, and irrelevant evidence in separate revisions | Rank/confidence changes only when justified and revision diff names the evidence responsible |
| `A05-T09` | Severity boundaries | Exact values below/equal/above thresholds plus missing/stale metric | Severity and provisional flag match policy for every boundary |
| `A05-T10` | Recommendation truth | Ask for checks/remediation with and without execution evidence | Suggested action is distinct from executed action; no completion claim without action evidence |
| `A05-T11` | Quality/calibration | Full gold-set evaluation by incident category and service | Meets top-1/top-3, unsupported-claim, abstention, and calibration targets with confidence intervals |

Evidence to close Area 5: per-rule metrics, invariant tests, causal
counterexample suite, grounding report, calibration plot, and gold-set report.

## Area 6 - LLM Boundary, Efficiency, And Model Operations

Hard safety/schema invariants must pass on every response. Probabilistic quality
is measured over the whole dataset and repeated on a designated unstable subset;
individual failures are not hidden by retries.

| Test ID | What we test | Method and environment | Pass condition |
| --- | --- | --- | --- |
| `A06-T01` | OpenAI-compatible adapter contract | Same request suite against fake server, local model, and approved provider sandbox | Normal/tool/error/usage/finish responses map to one internal contract |
| `A06-T02` | Structured output | Valid, truncated, malformed, refused, extra-field, unknown-citation, and oversized model responses | Only valid bounded schema reaches state; repair/retry count is bounded and visible |
| `A06-T03` | Timeout/retry/circuit/cancel | Provider delay, disconnect, 429, 5xx, stream stall, worker cancellation | Calls obey deadline/retry budget, release resources, and enter deterministic degraded flow |
| `A06-T04` | Usage and version ledger | Controlled response usage plus known price table | Stored provider/model/prompt/params/request/tokens/cost/latency/finish metadata reconcile exactly |
| `A06-T05` | Hard incident budget | Force call, token, tool, time, and currency limit individually and together | Limit cannot be exceeded beyond declared atomic margin; reviewer receives useful partial result |
| `A06-T06` | Provider outage fallback | Fail semantic, interpretation, RCA, and postmortem calls independently | Incident persists, never bypasses review, and returns correct deterministic/degraded state |
| `A06-T07` | Prompt injection/tool abuse | Adversarial corpus requests secrets, policy override, arbitrary query/URL/tool, or publication | Zero unauthorized tool/egress/publication; malicious text is cited only as data if relevant |
| `A06-T08` | Independent grounding | Generator deliberately outputs unsupported facts and citations | Separate validator catches every labeled critical violation before review/publication |
| `A06-T09` | Cache isolation | Same/different incidents, tenants, revisions, auth scopes, prompts, and models | Cache hit occurs only on exact safe key; no cross-boundary content is returned |
| `A06-T10` | Model/prompt regression | Gold suite on baseline and candidate configuration | Candidate meets all hard gates and approved non-inferiority/improvement bounds for quality, latency, and cost |
| `A06-T11` | Tiered routing | Strong deterministic, routine, ambiguous, and major incidents | Expected route is chosen; expensive route only occurs within policy and budget |
| `A06-T12` | Repeatability/flakiness | Repeat designated samples with fixed config and record all outputs | Invariant pass rate is 100%; quality variance stays below ratified limit and is reported |

Evidence to close Area 6: adapter contract result, provider fault matrix,
usage/cost reconciliation, injection report, grounding report, and comparative
model/prompt evaluation.

## Area 7 - Incident Memory And Knowledge Memory

| Test ID | What we test | Method and environment | Pass condition |
| --- | --- | --- | --- |
| `A07-T01` | Incident revision memory | Restart between every workflow stage and append observations after restart | Exact committed evidence/revision/review resumes; no loss, duplicate, or silent overwrite |
| `A07-T02` | Approved-only knowledge | Attempt ingestion from unapproved analysis, rejected draft, approved postmortem, and trusted runbook | Only explicitly approved/curated records become searchable knowledge |
| `A07-T03` | Authorization/filter-first | Cross-tenant/service/env/security-class retrieval attempts | Unauthorized candidates are removed before semantic search and never appear in context/telemetry |
| `A07-T04` | Retrieval relevance | Labeled query-to-memory relevance set with similar-but-wrong incidents | Precision/recall/stale-result/cross-service-contamination meet thresholds |
| `A07-T05` | Bounded cited retrieval | Many relevant records and oversized documents | Result count/context size stay bounded and every returned statement has source/relevance metadata |
| `A07-T06` | Supersession/expiry | Correct, disprove, expire, and replace knowledge records | Old record no longer influences new analysis except through explicit historical/audit view |
| `A07-T07` | Poisoning defense | Malicious retrieved instructions, forged provenance, and unauthorized update | Ingestion/retrieval policy blocks or quarantines input; no tool/policy override occurs |
| `A07-T08` | Retention/deletion cascade | Delete incident/subject/tenant under normal, backup, vector, cache, report, and checkpoint paths | All governed derivatives are removed or legally held exactly per policy with proof |
| `A07-T09` | Memory outage | Knowledge store unavailable, slow, partial, or returns malformed record | Analysis continues without memory, marks the gap, and stays inside latency budget |
| `A07-T10` | Value of memory | Blinded A/B on gold/shadow cases with and without retrieval | Measured quality/reviewer-time lift justifies added latency/cost and does not increase safety failures |

Evidence to close Area 7: retrieval benchmark, ACL isolation report,
poisoning suite, deletion manifest, outage test, and no-memory A/B report.

## Area 8 - Human Review And Postmortem Workflow

| Test ID | What we test | Method and environment | Pass condition |
| --- | --- | --- | --- |
| `A08-T01` | Identity and RBAC | Reviewer/operator/admin/unauthorized users attempt read, approve, edit, publish, retry, and delete | Only documented roles act on authorized incidents; every mutation is audited |
| `A08-T02` | Approve/reject revision loop | E2E rejection with feedback, revised analysis, then approval | Revision increments, feedback is retained, evidence/history remain visible, and approved ID is exact |
| `A08-T03` | Invalid hypothesis approval | Missing/nonexistent/ungrounded hypothesis and tampered request | Server rejects without state/publication change and records the attempt |
| `A08-T04` | Stale review | Open revision N, create N+1 from new evidence, then approve N | Conflict is shown; reviewer must view diff and explicitly act on current policy-permitted revision |
| `A08-T05` | Immutable review audit | Reconcile UI request, identity event, DB review record, incident revision, and trace | Identity/time/revision/hypothesis/evidence/decision/rationale/request ID are complete and immutable |
| `A08-T06` | Two approval gates | Approve analysis but not draft; alter draft after approval; approve exact draft | No external write before exact draft approval; any edit invalidates prior publish approval |
| `A08-T07` | Outbox/idempotent publication | Crash/retry concurrently before and after each destination acknowledgement | At most one logical message/document per idempotency key; terminal status is reconcilable |
| `A08-T08` | Partial publication failure | Slack succeeds/GitHub fails and reverse; retry only failed destination | UI/audit show per-destination truth; successful destination is not duplicated |
| `A08-T09` | Draft facts and structure | Valid/invalid postmortems with unsupported facts, missing sections/actions/owners/dates | Invalid draft cannot publish; valid draft cites exact approved evidence revision |
| `A08-T10` | Correction/retraction | Correct a published cause and simulate destination update failure | Original and correction remain audited; destination policy is followed idempotently |
| `A08-T11` | Accessibility/usability | Automated accessibility scan plus keyboard/screen-reader and large-incident human test | No critical accessibility defects; reviewer completes required decisions without hidden evidence |
| `A08-T12` | Reviewer effectiveness | Blinded pilot comparison against existing workflow | Meets agreed time, correctness, effort, trust, rejection, and override thresholds |

Evidence to close Area 8: RBAC matrix, full E2E traces, stale-review proof,
outbox reconciliation, accessibility report, and reviewer study.

## Area 9 - Security, Privacy, And Compliance

Every threat in the threat model must map to a preventive/detective control and
at least one automated test or a documented independent review procedure.

| Test ID | What we test | Method and environment | Pass condition |
| --- | --- | --- | --- |
| `A09-T01` | Threat-control coverage | Review threat model against test/control mapping | Every in-scope threat has owner, control, test, residual risk, and review date |
| `A09-T02` | Secret/PII leakage | Recursive fuzz corpus through intake, sources, state, model, telemetry, memory, reports, and publisher | Zero forbidden values in any sink; pseudonyms are stable only inside the approved boundary |
| `A09-T03` | Secure configuration | Start production with each missing/insecure secret, salt, origin, URL, store, auth, and publishing combination | Insecure setup fails startup/readiness with a redacted actionable error |
| `A09-T04` | Authentication/session/RBAC | Credential stuffing limits, expired/revoked session, role escalation, object-ID enumeration | Unauthorized access/mutation is always denied, rate-limited where required, and audited |
| `A09-T05` | Web mutation protection | CSRF, CORS, replay, forged origin, method/content-type confusion | No unauthorized state change and no permissive cross-origin credential behavior |
| `A09-T06` | Encryption and key rotation | Inspect transport/storage; rotate keys during staged reads/writes | Approved TLS/at-rest controls active; rotation retains availability and old key loses authority per policy |
| `A09-T07` | Egress/SSRF/tool restriction | URLs/IP encodings/redirects/DNS changes in every untrusted field and tool input | Requests reach only configured allowlisted destinations; metadata/internal networks are unreachable |
| `A09-T08` | Output/web security | Stored/reflected XSS, unsafe Markdown URL, traversal, header injection, huge render, malformed Unicode | Browser and filesystem receive safe encoded/bounded output; no execution or path escape |
| `A09-T09` | Supply chain | Dependency, image, license, secret, SAST, IaC, and SBOM scans | No unaccepted critical/high finding; artifact/SBOM/provenance match release digest |
| `A09-T10` | Audit integrity | Delete/modify/reorder audit data with application and operator roles | Unauthorized tampering fails or is detected; audit reconciliation reports no silent gap |
| `A09-T11` | Retention/deletion/compliance | Execute retention and data-subject/tenant deletion on all stores and backups | Policy deadline and exceptions are met with a machine-readable deletion/hold proof |
| `A09-T12` | Independent assessment | Security review and penetration test against release candidate | All critical/high findings fixed and retested; accepted lower risks have owner/expiry |

Evidence to close Area 9: threat-test matrix, leak scan, DAST/penetration report,
RBAC results, encryption/rotation proof, scan bundle, and deletion proof.

## Area 10 - State, Reliability, And Failure Recovery

| Test ID | What we test | Method and environment | Pass condition |
| --- | --- | --- | --- |
| `A10-T01` | Production database/checkpointer | Real supported database with migrations, pooling, concurrent workers, and restart | State is transactionally correct and resumable; supported isolation/version semantics hold |
| `A10-T02` | Worker lease/at-least-once | Duplicate deliveries, lease expiry, slow worker, worker death, and redelivery | One committed logical effect per event/revision; abandoned work is recovered within SLO |
| `A10-T03` | Crash-point recovery | Kill process before/after every node commit, interrupt, and side-effect boundary | Recovery reaches documented terminal/pending state with no accepted-event loss or duplicate effect |
| `A10-T04` | Retry classification | Inject invalid, auth, quota, timeout, 429, 5xx, DB conflict, and unknown error | Only classified transient errors retry; attempts/jitter/dead-letter match policy |
| `A10-T05` | Deadline/stuck work | Hang each connector/model/node and lose heartbeat | Deadline cancels work, releases lease/resources, and exposes degraded/failed state within SLO |
| `A10-T06` | State and evidence limits | Limit-1/limit/limit+1 for every configured size and count | Boundary behavior is documented; over-limit input is rejected/truncated safely and observed |
| `A10-T07` | Readiness/liveness | Fail DB, queue, migration, required secret, optional source, and model separately | Liveness reflects process; readiness reflects required dependencies/config exactly |
| `A10-T08` | Backup/restore | Restore point-in-time into isolated environment and reconcile event/revision/audit/outbox counts | Meets RPO/RTO and all referential/integrity checks; drill is repeatable from runbook |
| `A10-T09` | DB/network failover | Connection loss, failover, latency, partition, pool exhaustion, and recovery | No corrupted/lost committed state; bounded recovery and correct retry/backpressure |
| `A10-T10` | Alert-storm backpressure | Load beyond capacity with severity/tenant mix | Admission/queues stay bounded, priority policy holds, and recovery occurs without manual data repair |
| `A10-T11` | Graceful shutdown | Terminate API/workers during intake, collection, model call, review wait, and publish | Admission stops, committed work persists, leases release/checkpoint, no duplicate side effect |
| `A10-T12` | Soak/chaos | Multi-day staging run with scheduled dependency faults and state growth | No unbounded memory/storage/latency drift; error budget and recovery targets hold |

Evidence to close Area 10: crash matrix, queue/database reconciliation, recovery
times, backup restore report, failover traces, load graph, and soak report.

## Area 11 - Observability And Auditability

| Test ID | What we test | Method and environment | Pass condition |
| --- | --- | --- | --- |
| `A11-T01` | Structured log schema | Trigger every major path/error and validate emitted records | Required context fields exist, severity/category are correct, cardinality bounded, and leak scan clean |
| `A11-T02` | Metric correctness | Inject known counts/durations/tokens/cost/statuses then query metrics | Metrics reconcile with source records and use documented units/labels without unbounded cardinality |
| `A11-T03` | Trace propagation | Follow one incident across API, queue, worker, connectors, LLM, review, outbox | Correlation/incident/revision context links every span without exposing sensitive payloads |
| `A11-T04` | Dashboard queries | Seed known SLO/error/cost conditions in staging | Every panel returns expected value and handles no-data/stale-data explicitly |
| `A11-T05` | Alert rules and routing | Fire then recover every operational alert in a controlled drill | Alert reaches correct owner with actionable context; dedup/resolution/escalation work |
| `A11-T06` | Synthetic canary | Scheduled no-op incident through intake to review staging | Detects broken path within target time and proves publisher/remediation remain disabled |
| `A11-T07` | Audit completeness | Reconcile state-changing requests with immutable audit records | Exactly one complete audit event per mutation and no unexplained audit gaps |
| `A11-T08` | Telemetry privacy | Secret/PII corpus plus temporary debug mode test | Default telemetry contains no forbidden payload; debug access/expiry is authorized and audited |
| `A11-T09` | Sampling/retention | High volume, SEV1, failure, and routine traces over retention boundary | Sampling retains policy-required cases; expiration/storage cost match policy |
| `A11-T10` | Quality observability | Feed labeled approved/rejected/abstained/citation cases | Quality dashboard matches evaluator records for ranking, grounding, override, calibration, and cost |

Evidence to close Area 11: telemetry schema tests, metric reconciliation,
example linked trace, dashboard snapshots/queries, alert drill, and canary history.

## Area 12 - Tests, Evaluation, And Quality Gates

This area tests the test system itself. A green pipeline must mean the release
was genuinely evaluated, not that important suites silently skipped.

| Test ID | What we test | Method and environment | Pass condition |
| --- | --- | --- | --- |
| `A12-T01` | CI required checks | Deliberately fail format, type, unit, security, migration, budget, and eval checks | Each failure independently blocks merge/release and is visible to developers |
| `A12-T02` | Coverage quality | Branch coverage plus critical-module thresholds; inspect uncovered risky paths | Thresholds pass and no P0 control is excluded/covered only by trivial assertions |
| `A12-T03` | Gold dataset validity | Schema, duplicate, leakage, label consistency, category/service balance, provenance checks | Dataset is versioned, valid, approved, representative, and reproducibly loadable |
| `A12-T04` | Label quality | Blind dual review on sample plus adjudication and agreement measurement | Agreement meets ratified threshold; disagreements/ambiguous truth are retained explicitly |
| `A12-T05` | Evaluator correctness | Hand-calculate small cases for top-k, citation, abstention, calibration, latency, and cost | Evaluator exactly matches expected scores and rejects malformed/missing result records |
| `A12-T06` | End-to-end matrix | Success, reject/revise, abstain, missing sources, model outage, stale review, and publish failure | All workflows terminate in the specified persisted state with correct audit/side effects |
| `A12-T07` | Test isolation | Randomize order, parallelize, and run twice from clean environments | Same outcomes without shared state, real external effect, or order dependency |
| `A12-T08` | Flake detection | Repeated deterministic and designated probabilistic subsets | Deterministic suite has zero flakes; probabilistic variance is recorded and within limit |
| `A12-T09` | Mutation/property effectiveness | Mutate safety/scoring/redaction/idempotency logic and generate boundary inputs | Tests kill the ratified mutation percentage and preserve declared invariants |
| `A12-T10` | Release gate | Create candidate missing/failed test artifact and one below quality/cost target | Promotion is blocked; exception requires recorded scope, owner, expiry, and approval |
| `A12-T11` | Production artifact identity | Compare tested artifact digest/config migration with deployed release | Exact artifact/config is deployed; drift is detected and blocks/alerts according to policy |

Evidence to close Area 12: CI configuration demonstration, coverage/mutation
reports, dataset validation, evaluator unit tests, flake report, and release-gate
failure demonstration.

## Area 13 - Performance And Cost Control

| Test ID | What we test | Method and environment | Pass condition |
| --- | --- | --- | --- |
| `A13-T01` | Per-node benchmark | Small/routine/large/ambiguous fixtures with source/model timing captured | p50/p95/p99, memory, state size, source calls, tokens, tools, and cost are reported per node/class |
| `A13-T02` | Intake latency/throughput | Load at expected rate and 130% capacity with realistic batches | Durable acknowledgement and error-rate SLOs hold; no data loss or retry amplification |
| `A13-T03` | Analysis latency | Controlled fast/slow/partial sources and model routes | p50/p95 targets hold or explicit degraded deadline occurs; bottleneck trace is available |
| `A13-T04` | Large incident bounds | Maximum logs/groups/services/timeline/revisions/context/output | Memory/state/context stay below caps; rare evidence survives; output remains reviewable |
| `A13-T05` | Real token/cost accounting | Reconcile provider usage/billing sample with internal ledger | Difference stays inside ratified rounding tolerance; budget uses authoritative measured usage |
| `A13-T06` | Budget enforcement | Cross each severity-specific query/token/call/time/cost boundary | Agent stops expansion before excess and returns partial evidence/budget reason |
| `A13-T07` | Early exits and routing | Empty, deterministic-strong, unchanged revision, resolved-low-impact, and ambiguous cases | Expected calls/tools are skipped or selected; quality does not regress beyond limit |
| `A13-T08` | Cache performance/correctness | Hit/miss/expiry/invalidation under concurrency and auth/revision changes | Latency/call saving measured; no stale, unauthorized, or cross-incident result |
| `A13-T09` | Alert storm/capacity | Sustained mix beyond quotas followed by recovery | Priority/fairness/backpressure hold, queues drain within target, cost ceiling is protected |
| `A13-T10` | Soak and growth | Multi-day representative traffic with review waits and retained state | No unacceptable resource drift; projected monthly storage/model cost fits capacity plan |

Evidence to close Area 13: reproducible benchmark definition, raw result files,
SLO graphs, provider reconciliation, capacity model, and cost/quality comparison.

## Area 14 - Packaging, Deployment, And Operations

| Test ID | What we test | Method and environment | Pass condition |
| --- | --- | --- | --- |
| `A14-T01` | Reproducible dependency build | Build twice from clean runners with locked dependencies | Dependency set and application artifact digest are identical or reproducibly explained |
| `A14-T02` | Container security/runtime | Image scan, non-root/read-only checks, dropped capabilities, signal and health tests | No unaccepted findings; process runs without root and shuts down correctly |
| `A14-T03` | Production config validation | Matrix of valid and insecure/missing environment settings | Valid config starts; every insecure combination fails before readiness with redacted reason |
| `A14-T04` | Environment isolation | Attempt cross-environment DB/source/model/publisher access from test/staging | Access fails; identifiers/credentials/destinations cannot collide with production |
| `A14-T05` | IaC/policy | Validate/plan plus security/policy tests for network, storage, secrets, IAM, scaling | No unapproved drift, public exposure, wildcard permission, unencrypted store, or missing limit |
| `A14-T06` | Database migration | Upgrade from supported prior versions, operate mixed rollout if supported, and rollback/forward-fix | No data/invariant loss; compatibility window and recovery procedure work |
| `A14-T07` | Deployment smoke/canary | Deploy exact candidate, run canary, observe gates, then promote | Intake/no-op workflow/telemetry pass and candidate metrics stay within promotion thresholds |
| `A14-T08` | Rollback | Inject post-deploy failure and execute documented rollback | Previous release restored inside target without corrupting newer incident state |
| `A14-T09` | Kill switches | Exercise LLM, expansion, memory, review UI, and each publisher switch during work | Each stops only intended capability quickly, is audited, and leaves recoverable state |
| `A14-T10` | Secret rotation | Rotate webhook, identity, DB, source, model, and publisher secrets | No unauthorized overlap beyond policy and no unacceptable availability loss |
| `A14-T11` | Autoscaling/capacity | Scale up/down under queue load and long review waits | No duplicate/lost work; scale behavior respects quotas, leases, and shutdown semantics |
| `A14-T12` | Operator runbooks | Game days for backlog, stuck job, DB/model/source outage, bad prompt/rule, compromised secret, duplicate publish | On-call detects, mitigates, communicates, and recovers within target using the runbook |

Evidence to close Area 14: build digests/SBOM, image/IaC scans, config matrix,
migration report, canary/rollback trace, kill-switch record, and game-day report.

## Area 15 - Documentation And Governance

| Test ID | What we test | Method and environment | Pass condition |
| --- | --- | --- | --- |
| `A15-T01` | Documentation integrity | Markdown/link/code-example/config-schema checks in CI | No broken internal links, invalid examples, stale generated schema, or missing required document |
| `A15-T02` | Architecture/schema accuracy | Trace representative workflow against diagram/state/schema documentation | Every trust boundary, store, transition, model call, human gate, and side effect matches implementation |
| `A15-T03` | ADR coverage | CI/review checklist for architecture-changing files/config | Required decision has accepted ADR with context, alternatives, consequences, owner, and date |
| `A15-T04` | Fresh-environment setup | A person/clean runner follows only documented setup for local and staging | System and tests start without undocumented commands, access, or secrets |
| `A15-T05` | Reviewer documentation | New reviewer completes approve/reject/stale-revision/data-gap scenarios | Correct decisions are made and responsibilities/uncertainty are understood |
| `A15-T06` | Runbook usability | Operator unfamiliar with the implementation executes game-day recovery | Recovery succeeds within target and every confusing/missing step becomes a tracked fix |
| `A15-T07` | Ownership/expiry | Automated scan of rules, runbooks, services, knowledge, and policies | Every governed item has active owner/review date; expired content is blocked or flagged |
| `A15-T08` | Data inventory reconciliation | Compare schemas/IaC/runtime data flows with inventory | Every field/store/processor/access/retention/deletion path is represented; drift blocks release |
| `A15-T09` | Release evidence completeness | Validate release manifest against required tests, evals, scans, drills, dashboards, and approvals | No missing/expired/failed required artifact; approver identities and artifact digest match release |
| `A15-T10` | Known-limitations/change log | Compare candidate diff/evaluation failures with published release notes | Material behavior/model/rule/schema/security/quality changes and limitations are documented |

Evidence to close Area 15: documentation CI report, architecture walkthrough,
fresh-setup result, reviewer/operator exercise, inventory diff, and validated
release manifest.

## Execution Cadence

| Cadence | Required suites |
| --- | --- |
| Every pull request | L0, L1, affected L2, prompt budgets, deterministic evaluation subset, leak/security unit tests |
| Merge to main | Full L0-L3, migration checks, E2E happy/reject/degraded paths, candidate-versus-baseline eval |
| Nightly | Full connector integration, provider sandbox, gold set, injection corpus, concurrency/crash subset |
| Weekly | Dependency/image/IaC scans, load test, deletion/retention check, synthetic restore sample |
| Before shadow | Full P0 suite, security review, restore, alert storm, model/source outage, external-effect blocking proof |
| During shadow | Continuous SLO/cost/leak monitoring; labeled comparison and weekly quality review |
| Before pilot/GA | Full release suite, soak, chaos, penetration/retest, backup restore, game day, human evaluation, sign-off |
| After deployment | Artifact/config identity check, smoke/canary, SLO/error-budget watch, rollback window |

## Implementation Plan For The Test System

### Phase 1 - Build The Fast Safety Harness

- Add one test runner entry point for unit, contract, integration, E2E,
  security, evaluation, load, and release suites.
- Add schema factories and deterministic fixture builders rather than copying
  unstructured dictionaries into every test.
- Add isolated temporary storage and reset helpers; tests must not depend on
  the existing `data/`, `output/`, or developer model process.
- Add CI for compile, lint/type, unit, prompt budget, redaction, grounding,
  state-transition, and readiness-document checks.
- Keep the 73 existing test methods mapped to stable test IDs and extend their
  coverage without replacing the verified MySQL, security, and contract
  baselines.

### Phase 2 - Prove Incident Correctness First

- Implement Area 2 lifecycle/API tests, Area 4 evidence/provenance tests, and
  Area 5 hypothesis/grounding tests alongside the new schemas and revision
  model.
- Build fake source/model/publisher servers that record requests and can inject
  delay, malformed response, rate limits, connection loss, and partial success.
- Add crash hooks around state/outbox boundaries so recovery tests are
  deterministic rather than relying on random process kills.

### Phase 3 - Add Production Dependencies

- Run database, queue, object store, identity, Loki, Prometheus, and other
  supported connector versions in ephemeral integration environments.
- Add migration, concurrency, lease, outbox, backup/restore, and environment
  isolation suites.
- Add production configuration validation and reproducible container tests.

### Phase 4 - Build The AI Evaluation System

- Create and review the gold dataset and evaluator unit tests.
- Establish baseline results for deterministic-only, local-model, and approved
  provider configurations.
- Add structured-output, grounding, injection, abstention, calibration,
  usage/cost, and regression gates.
- Use a small deterministic subset on each change and the full set nightly and
  before release.

### Phase 5 - Verify Operations In Shadow

- Prove external writes are blocked by code, credentials, and network policy.
- Run synthetic canaries, load/failure drills, restore, and game days.
- Compare the agent with human incident conclusions without showing the agent’s
  result until labels are recorded where practical.
- Promote only when the full Shadow-Ready DoD and ratified thresholds pass.

## First Tests To Implement

Implement these in this order because they protect the project’s central
purpose and unblock later architecture:

1. `A02-T06` incremental observations and analysis revisions.
2. `A02-T05` exact duplicate/idempotency behavior.
3. `A02-T08` lifecycle state-machine invariants.
4. `A04-T02` recursive redaction and sink leak scan.
5. `A04-T06` stable evidence IDs and append-only corrections.
6. `A04-T08` citation resolution and cross-incident blocking.
7. `A05-T05` independent grounding gate at every generated stage.
8. `A05-T06` insufficient-evidence abstention.
9. `A06-T03` model timeout/retry/circuit/degraded behavior.
10. `A08-T06` separate analysis and exact-draft publication approval.
11. `A10-T03` deterministic crash-point recovery.
12. `A12-T10` a release gate that is proven to fail closed.

## When A Readiness Checkbox May Be Marked Complete

Use this close-out sequence for every criterion:

1. Add the criterion ID to the implementation change.
2. Add or update mapped automated test IDs.
3. Pass all required L0-L4 tests on the exact artifact.
4. Pass relevant L5 security/reliability/performance tests.
5. Collect required L6 shadow/human evidence where applicable.
6. Confirm telemetry and operator/reviewer documentation.
7. Attach the test manifest and reports to the release/change record.
8. Have the accountable owner review the evidence.
9. Only then change `[ ]` to `[x]` in `PRODUCTION_READINESS.md`.
