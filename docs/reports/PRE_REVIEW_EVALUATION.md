# Pre-review pipeline evaluation

This checkpoint covers the path from alert ingestion through the analysis shown
to a human reviewer. The local pipeline and bounded OpenAI provider path are
included. RCA, postmortem generation, publication, and hosted deployment are
deliberately outside this checkpoint.

## What is implemented

- Loki collection uses bounded time slices plus explicit high-signal queries
  instead of taking only the latest `N` rows.
- The mock and synthetic path uses the same deterministic representative
  sampling policy.
- Source timestamps are promoted to canonical UTC event time before ordering,
  bucketing, correlation, and scoring. The original timestamp remains in
  canonical evidence.
- Aggregation preserves SQLSTATE, HTTP status, and error-code distinctions
  before removing volatile numbers.
- Evidence graph edges state whether evidence precedes, follows, or coincides
  with the alert anchor; they no longer claim every event happened after it.
- Bounded targeted log results returned during semantic correlation are
  redacted, deduplicated, normalized, grouped, detected, correlated, and
  rescored before interpretation.
- Degraded/no-LLM output only renders actual deterministic candidates or an
  abstention. It does not create generic causes, percentages, or remediation.

## Deterministic synthetic gate

Run:

```bash
python scripts/evaluate_pre_review.py
```

The current suite contains eight cases:

1. a rare failure inside 5,000 common records;
2. two materially different SQLSTATE errors;
3. a deployment that occurs after the symptom;
4. mixed time zones and out-of-order delivery;
5. a cross-service trace pivot;
6. contradictory log and metric evidence;
7. insufficient evidence requiring abstention; and
8. a truncated sample whose counts must remain honest.

These are exact contract tests. They are useful for regression prevention but
do not measure real-world incident accuracy.

Run the complete local workflow only up to the reviewer interrupt with:

```bash
python scripts/run_fixture.py \
  --fixture fixtures/latency_alert.json \
  --no-llm \
  --stop-at-review
```

This path performs no approval, RCA, postmortem generation, or publication.

## Public-data robustness gate

The selected first corpus is LogHub HDFS 2k. Fetch and evaluate it with:

```bash
python scripts/fetch_public_logs.py \
  --dataset loghub_hdfs_2k \
  --accept-research-license

python scripts/evaluate_public_logs.py \
  --dataset loghub_hdfs_2k
```

Raw files remain local and ignored by git. A receipt records URL, retrieval
time, byte count, SHA-256, intended uses, and prohibited claims. Before pipeline
processing, the adapter minimizes IPv4 addresses, HDFS block IDs, and user path
names.

The report measures:

- source/sample row and level counts;
- timestamp parsing to UTC;
- identifier minimization;
- order-invariant grouping;
- inferred-group purity against upstream event IDs;
- cross-event collisions; and
- fragmentation, meaning how many inferred fingerprints one upstream event
  template becomes.

The first versioned gate requires at least `0.98` weighted event-ID purity, zero
cross-event collision groups, and no more than `2.0` inferred fingerprints per
source event on average. These are regression thresholds for this corpus, not
universal production-quality targets.

This corpus is not a causal gold set. Its event IDs describe log templates, not
incident causes, and it has no reviewed deploy/metric/trace timeline. It must
not be used to claim root-cause precision, model training quality, or production
representativeness.

### Hadoop multi-container corpus

The user-managed LogHub Hadoop folder can be evaluated in place without copying
its raw contents into the repository:

```bash
python scripts/evaluate_public_logs.py \
  --dataset loghub_hadoop \
  --path ../Hadoop \
  --sample-limit 200 \
  --output output/hadoop-pre-review-evaluation.json
```

Each application directory is treated as one offline incident boundary.
`abnormal_label.txt` is loaded only after pipeline processing as held-out truth;
workload and failure labels are never placed in alert, log, grouping, scoring,
or model context.

The first run covers 55 applications, 978 container files, 394,310 physical
lines, and 180,897 parsed events. Parser, label coverage, high-signal retention,
and order-invariance gates pass. The initial generic deterministic rules
abstained on all 55 cases. The current pipeline additionally promotes only
direct matches from the versioned generic signal catalog to unverified
hypothesis candidates; it does not add rules based on the Hadoop labels.

The corpus exposed and fixed one unsafe shortcut: Hadoop's ApplicationMaster
can kill a container with exit code 137 even when there is no OOM evidence.
Exit code 137 alone therefore no longer triggers the `oom-killed` rule; explicit
`OOMKilled`, out-of-memory, memory-cgroup, or kernel-kill evidence is required.

The typed review boundary can be evaluated against all 55 applications with:

```bash
python scripts/evaluate_hadoop_typed_review.py \
  --cases 55 \
  --output output/hadoop-typed-review-all-55.json
```

Current result:

| Measure | Result |
|---|---:|
| Grounding pass rate | 100% (55/55) |
| Unknown evidence IDs | 0 |
| Unsupported prediction rate | 0% |
| Exact injected-label accuracy | 32.73% |
| Exact accuracy where impact is recoverable | 100% (18/18) |
| Exact result or honest abstention | 98.18% (54/55) |
| Supported label mismatches | 0 |
| Recovered faults retained as observation-only | 15 cases |
| Label/evidence conflicts | 25 |

The result is label-blind until scoring. `observed-signal/v1` separates a
direct fault observation from a cause candidate. Hash-minimized workload and
execution IDs support incident-local entity links without exposing Hadoop
application/container IDs. `impact-assessment/v1` and `signal-impact-link/v2`
record explicit operation effects, adverse lifecycle links, and later
recovery/success. Repeated shapes
are represented as `event-burst/v1` onset/end/peak/count summaries rather than
being treated as independent proof.

### HDFS_v1 and OpenStack impact generalization

The same label-held-out typed boundary now runs against local HDFS_v1 and
OpenStack corpora. HDFS evaluation selected 20 anomaly and 20 normal blocks;
9 direct storage I/O/metadata observations appeared only in the selected
anomaly cases. OpenStack evaluated all 4 labeled anomaly instances and 12
normal instances. Lifecycle sequences are retained as outcome context, never
fault observations.

A subsequent label-last full-corpus audit covered 2,064 complete OpenStack
spawn traces. The four labeled anomalies had a 37.302 s median versus 20.384 s
for 1,868 labeled normals. All four remained at or above the 98.46th
percentile against peers in the same source file and at or above the 96.15th
percentile within the same hour. This rules out the obvious file/time
confounder in this corpus, but four anomalies are still insufficient for a
fixed global seconds threshold or a root-cause rule.

The same audit scanned all 575,061 HDFS event traces. Typed storage markers had
97.67% failure precision and 57.42% failure recall after truth join. `E7`
appeared in 3,303 failed and zero successful traces, while metadata markers
`E20/E28` also appeared in 231 successful traces. The implementation boundary
is therefore narrow: `E7` may establish an observed block-operation failure;
metadata remains observation-only without independent adverse outcome.
Generic later-success markers are not accepted as recovery evidence.

The audited findings are now implemented. `operation-duration-feature/v1`
uses a leave-one-out `peer-duration-baseline/v1` with at least 20 peers,
percentile, duration ratio and MAD-based robust z. It persists baseline and
source provenance, uses no truth labels, and has no fixed seconds threshold.
The rerun established peer-relative latency impact for 4/4 OpenStack anomalies
and 0/12 selected normals. Successful completion remains compatible with a
slow-operation impact. None became a root-cause candidate.

For HDFS, the explicit stream-read failure now establishes
`block_operation_failed`. All 6 selected direct storage-I/O observations had
established operation impact, while all 3 storage-metadata observations
remained `not_established`. None became a root-cause candidate. Both reruns
retained 100% grounding and impact-contract pass rates with no identifier
leaks, unknown evidence IDs, or label-derived baseline decisions.

A four-case blind OpenAI smoke test then exercised those richer evidence
packs. Provider transport, Pydantic Structured Output parsing, raw boundary
decisions, grounding, and final boundary decisions passed 4/4. The raw model
abstained in every case, produced zero hypotheses, cited zero unknown evidence
IDs, proposed zero non-read-only steps, and acknowledged the relevant
observation in every case. Provider-reported usage was 9,078 total tokens.

The four-case run exposed one wording defect rather than letting grounding
mask it: the model called a successful but slow OpenStack spawn “recovered
slow operation latency.” The contract now separates `successful_completion`
from recovery. A completed duration remains an established historical
measurement even if the workload later succeeds or resumes.

The follow-up OpenStack rerun retained 4/4 anomaly and 0/12 selected normal
latency observations with `impact=established`, `recovery=false`, and
`successful_completion=true`. A larger 12-case blind OpenAI regression then
passed provider transport, schema parsing, raw boundary, grounding, and final
boundary checks in 12/12 cases. All 4/4 latency answers described a slow
operation that completed successfully; zero called it recovered. The run
produced zero hypotheses, unknown evidence IDs, non-read-only proposals, or
unsupported percentage claims across 27,451 provider-reported tokens.

Both datasets pass grounding, typed-impact, evidence-ID and identifier
minimization gates. The reports explicitly prohibit root-cause accuracy claims
because the source labels contain only normal/anomaly.

A recovered direct fault without a linked adverse lifecycle event remains
visible but cannot by itself create an approvable cause hypothesis. Competing
observed failure categories cause abstention even if only one has an eligible
candidate. This reduced supported label mismatches from five to zero. The lower
exact injected-label accuracy is the intentional result of replacing unsafe
classification with observation-only or abstention; the impact-recoverable
subset is 18/18 exact.

`abnormal_label.txt` is useful held-out truth, but it is not a perfect causal
gold set for each log line. It names the injected application-level condition.
It does not separately label every observed fault, the affected entity, the
causal window, or the final job outcome. In the raw corpus:

- the expected direct signal exists for 13/28 `machine_down`, 5/7
  `network_disconnection`, 0/9 `disk_full`, and a positive success signal for
  10/11 `normal` applications;
- some applications contain direct faults from more than one class;
- some abnormal applications reach `SUCCEEDED`; and
- some applications labelled `normal` still contain direct lost-node or
  connection-failure observations.

Therefore exact injected-label accuracy is not a standalone pipeline-quality
measure. Entity/time/recovery links are now implemented for the fields present
in the container corpus. The remaining data work is to obtain negative
lifecycle/host/storage telemetry, especially for `disk_full`. A later
controlled scenario set should expose separate
`injected_fault`, `observed_faults`, `job_outcome`, onset, affected entity, and
expected evidence fields.

Do not derive new label-specific production rules on these same 55
applications. Any further rule development needs a versioned
development/validation/test split by application and workload.

### OpenAI sandbox profile

`config/openai_sandbox.env.example` contains a bounded, no-tool starting profile.
The real API key belongs only in the untracked local `.env`. The first provider
evaluation should use a small stratified subset, one call per case, and compare
model output with held-out truth after the call.

## What remains before broader OpenAI use

The next data-quality milestone is a versioned incident gold set containing
synthetic multi-source cases and, later, approved sanitized incident replays.
Each case needs expected evidence, causal and non-causal relations, expected
abstention, and a reviewer decision.

Before broadening OpenAI use beyond the bounded evaluation cases, the
pre-review gate should additionally prove:

- structured JSON-body parsing and explicit connector schema IDs;
- measured unknown-schema, missing-label, freshness, duplicate, and clock-skew
  rates;
- a healthy metric baseline and trace-backend contract;
- revisioned provenance for each iterative targeted query;
- grouping precision and fragmentation thresholds across multiple log
  families; and
- a typed model response plus independent citation/grounding validation.

Hosted deployment remains the final step after these local and provider-sandbox
gates pass.

## Loghub cross-system generalization run

The next label-last run added HDFS_v3 TraceBench, BGL, and ZooKeeper without
adding dataset-specific production detection rules first.

- ZooKeeper parsing produced 68,762 events and joined 5,618 continuation lines
  from 74,380 physical lines. Six deterministic warning-bearing ten-minute
  windows were reviewed. The corpus has no source truth, so this is a parser,
  retention, and abstention test only.
- BGL parsing accepted all 4,747,963 source lines and found 14,494 five-minute
  windows. Eight windows containing held-out alert tags and eight without alert
  tags were selected by stable hash.
- TraceBench selected eight source-labeled failed tasks from eight different
  injected fault families and eight normal tasks. The adapter scanned 1,009,435
  event rows for the chosen traces plus 766,845 rows during held-out task-label
  selection. Fault-family and task truth were never included in pipeline or
  model input.

All 38 deterministic case reviews passed grounding and typed-impact contracts
with no unknown evidence IDs, raw identifier leaks, or label-derived
candidates. That safety result must not be confused with signal coverage:

- TraceBench recognized a catalog signal in 3/8 failed tasks and 0/8 normal
  tasks. All recognized signals were network transport. Five storage-related
  failures such as `OP_READ_BLOCK`, no live block node, block-sender failure,
  and missing/corrupt block behavior were retained as error groups but had no
  typed catalog observation.
- BGL recognized a catalog signal in 1/8 alert windows and 0/8 non-alert
  windows. Unclassified alert windows contained concrete error groups such as
  Lustre mount failures, machine-check interrupts, parity faults, and core
  generation. BGL alert tags are not root-cause truth, so 1/8 is signal
  coverage rather than causal accuracy.
- ZooKeeper retained warning bursts such as connection breakage and
  end-of-stream exceptions, but 0/6 selected windows mapped to the current
  catalog. With no labels, no detection-accuracy percentage is claimed.

TraceBench also exposed a time-quality boundary. Its event clocks are
host-local and are not assumed globally comparable. The current adapter assigns
the trace-level coarse `FirstSeen` timestamp to each event and records that
limitation. Consequently these runs validate trace-ID grouping and evidence
retention, not cross-host event ordering or latency. A trace-graph-aware clock
model is required before TraceBench can validate fine-grained timelines.

A seven-case official OpenAI evaluation then covered a detected TraceBench
failure, an undetected TraceBench failure, a normal TraceBench control, a
detected BGL alert, an undetected BGL alert, a BGL non-alert control, and an
unlabeled ZooKeeper warning window. Provider transport, Structured Output
parsing, raw supported/abstained boundaries, final boundaries, and grounding
passed 7/7. The two catalog-supported cases returned one grounded hypothesis
each; all five unsupported/control cases abstained with zero hypotheses.
There were no unknown evidence IDs or unsupported numeric claims. The run used
15,939 provider-reported tokens and 53.631 seconds of summed provider latency.

The result is intentionally mixed: the model boundary is behaving safely, but
the deterministic vocabulary is too narrow for the new systems. OpenAI does not
and should not bypass that boundary to invent causes from unclassified errors.
The next implementation should add source-agnostic observation types for
unclassified error/fatal groups, distributed-storage read/block failures,
hardware/machine-check faults, and connection-break/end-of-stream events.
Those observations must remain separate from root-cause eligibility until
entity, temporal, and adverse-outcome evidence establishes impact.

### Generic system-observation follow-up

The source-agnostic follow-up is now implemented in signal catalog v4. It adds:

- an `unclassified_error` fallback only when a structured
  `error`/`fatal`/`critical` group has no more specific catalog match;
- distributed-storage block/read, integrity, and mount-failure observations;
- connection-broken and stream-ended observations;
- machine-check/parity and process-failure observations; and
- timestamp ordering scopes (`global`, `source_relative`, and `trace_only`)
  propagated from normalized evidence into groups and model context.

The new families are observations, not additions to the deterministic
root-cause whitelist. Trace-only timestamps are explicitly rejected for
cross-event lifecycle ordering. Source-relative timestamps can only be compared
inside the same source dataset.

The same held-out cases improved as follows:

- TraceBench moved from 3/8 to 8/8 failed tasks containing typed observations
  while remaining 0/8 on normal tasks. The five newly visible storage cases
  remain abstained; only the same three independently whitelisted network cases
  are supported.
- BGL moved from 1/8 to 8/8 alert windows containing typed observations.
  Three non-alert windows also contain corrected hardware/error observations;
  all remain `impact=not_established`, candidate-ineligible, and abstained.
  These are not counted as causal false positives because BGL alert tags are
  not task-level root-cause truth.
- ZooKeeper now has typed observations in 5/6 selected windows. All six
  observations remain `impact=not_established` with no candidate.

All reruns retained 100% grounding and impact-contract pass rates. A second
seven-case official OpenAI gate passed provider transport, schema, raw/final
status boundaries, and grounding in 7/7 cases. The two pre-existing supported
network cases produced one grounded hypothesis each. The storage-only HDFS
failure, BGL alert-only error, corrected BGL hardware control, normal HDFS
control, and unlabeled ZooKeeper stream window all abstained with zero
hypotheses. The run had zero unknown evidence IDs and zero unsupported numeric
claims across 19,115 provider-reported tokens and 32.582 seconds of summed
provider latency. The full repository regression suite passes 172/172 tests.

### Correlated observation-pattern follow-up

The next pre-review layer now correlates repetitive direct observations without
changing their evidentiary or causal meaning. `observation-pattern/v1` groups
only observations with the same incident-local service, signal family, status,
scope, impact status, and cause-candidate eligibility. Each pattern contains:

- a stable content-derived pattern ID;
- the number of distinct event groups and summed source occurrences;
- first and last observed timestamps only when the source ordering is
  comparable;
- unique entity counts with bounded samples;
- propagated timestamp quality, ordering scope, and source dataset;
- bounded event and observation references; and
- up to three deterministic representative evidence rows.

`trace_only`, unknown, or otherwise non-comparable clocks receive
`time_span_status=not_comparable` and no aggregate first/last timestamp.
Source-relative time spans require one shared source dataset. Individual
representative rows retain their own timestamps without implying cross-host
order.

Every pattern is explicitly `causal_status=not_established`. Pattern
correlation is presentation and context compression only. Candidate generation
still consumes the original typed observations, so a pattern cannot promote an
unclassified error, cross a service or impact boundary, or create a new cause.
Order-invariance and candidate-isolation tests enforce those constraints.

The label-last dataset rerun produced:

| Dataset | Raw observations | Correlated patterns | Grounding | Impact contract |
| --- | ---: | ---: | ---: | ---: |
| HDFS v3 TraceBench | 38 | 14 | 100% | 100% |
| BGL | 160 | 16 | 100% | 100% |
| ZooKeeper | 6 | 6 | 100% | 100% |

BGL is the main gain: 149 `unclassified_error` observations across five cases
become five case-local error patterns instead of consuming the review context
as independent facts. Across every held-out case, deterministic candidate
categories and final review status are identical to the pre-correlation run.
The evidence pack now uses patterns for repeated observations and retains
per-observation detail only for candidate-eligible or measured-feature evidence.
The BGL evidence-pack average is 3,573 characters versus 3,590 before
correlation, while now also carrying entity spread, time quality, occurrence
counts, and stable representative evidence.

A third seven-case official OpenAI gate passed provider transport, Structured
Output parsing, raw/final status boundaries, and grounding in 7/7 cases. The
same two independently supported network cases returned one grounded
hypothesis each. The other five storage-only, error-only, normal, and unlabeled
control cases abstained with zero hypotheses. The run produced zero unknown
evidence IDs and zero unsupported percentages across 19,018 provider-reported
tokens and 59.076 seconds of summed provider latency.

The full repository regression suite now passes 174/174 tests. Prompt-budget
checks remain within the configured limits. The next pipeline-quality step is
to measure grouping fragmentation and over-merging against additional system
datasets or a small manually annotated event-pair set; it should not be another
expansion of the cause-candidate whitelist.

### Full production-path HDFS to OpenAI to review run

The reusable full pre-review runner now exercises the production nodes instead
of only the evaluation adapter:

```bash
python scripts/evaluate_full_pre_review.py \
  --sample-limit 200 \
  --output output/full-pre-review-e2e.json \
  --html-dir output/full-pre-review-e2e
```

It starts with real HDFS v3 TraceBench logs, then runs alert ingestion,
collection planning, normalization, grouping, deterministic detection,
observation correlation, candidate scoring, evidence-pack construction,
semantic tool use, bounded targeted-evidence integration, structured
interpretation, independent grounding, and HTML review generation. Held-out
fault metadata is joined only in the final evaluation report and is not exposed
to any pipeline or model stage. The run stops before approval, RCA, postmortem,
publication, or deployment.

The first end-to-end attempt exposed a transport mismatch: the evaluation
scripts used the OpenAI Responses API while the production nodes still used
Chat Completions. Their failure was hidden by the safe deterministic fallback,
which produced a plausible review with zero provider calls. The production
client and both tool loops now use the Responses API and preserve response
output items, including reasoning and function-call output, between tool
rounds. Provider usage is recorded from Responses input/output token fields.

The final two-case run produced:

| Measure | Result |
| --- | ---: |
| Cases | 2 |
| Grounding passes | 2/2 |
| Final boundaries | 1 supported, 1 abstained |
| Grounded hypotheses | 1 |
| Unknown evidence IDs | 0 |
| Semantic tool calls | 4 |
| Actual provider calls | 6 |
| Provider-reported tokens | 14,961 |
| Wall time | 26.445 s |

The supported network case reduced 189 source records to 71 representative
records, 24 groups, two typed observations, and two observation patterns. It
retained the independently eligible `network_disconnection` candidate and
produced one grounded hypothesis. The storage case reduced 98 source records
to 48 representative records, 14 groups, seven observations, and two patterns.
It had no eligible causal candidate, so the final answer correctly abstained
with zero hypotheses.

The semantic loop inspected real `log-*` evidence in both cases. It integrated
zero new records because its bounded searches returned no usable records beyond
the existing sample. This is an important value boundary: in these cases the
model organized and checked already-collected evidence, but did not discover a
new fact. Improving connector coverage and data discrimination is therefore
more valuable than adding more permissive prompts or cause rules.

The generated HDFS review pages are now source-agnostic. Payment, SQL, and
`orders-api` verification examples were removed; verification commands are
derived from actual candidate and observation-pattern evidence IDs. The
decision dropdown exposes only hypotheses that actually exist, and abstained
reviews cannot be approved.

The full repository regression suite now passes 177/177 tests. The configured
prompt budgets also pass: interpretation 4,678 characters, RCA 4,047,
postmortem 3,743, and evidence pack 4,192.

### Public grouping and thinning gate

The next data-quality gate now measures the log reduction layer directly:

```bash
python scripts/evaluate_grouping_quality.py \
  --dataset all \
  --sample-limit 200 \
  --output output/grouping-quality-all.json
```

The public portion uses HDFS 2k upstream human template IDs and TraceBench's
upstream preprocessing event proxy. Inferred production fingerprints are
created before those source labels are joined. Pairwise precision measures
over-merging, pairwise recall measures fragmentation, and separate coverage
metrics verify whether general, rare, and high-signal event shapes survive
bounded representative sampling.

The first run exposed a real thinning defect. A 200-row HDFS 2k sample retained
every high-signal template but only 11/14 total templates. The sampler now
reserves bounded representatives for general event shapes after protecting
boundaries, typed signals, and high-signal shapes. The rerun retains 14/14
templates, all rare templates, and all high-signal templates.

The public results after the change are:

| Dataset | Rows | Event-label coverage | Pair precision | Pair recall | Collision groups |
| --- | ---: | ---: | ---: | ---: | ---: |
| HDFS 2k | 2,000 | 100% (14/14) | 100% | 96.60% | 0 |
| HDFS v3 TraceBench | 1,854 | 100% (75/75) | 100% | 98.83% | 0 |

HDFS 2k still maps two source templates to multiple conservative fingerprints:
allocation paths produce six shapes and block deletion paths produce two. They
remain separate because the differing paths can represent meaningful workload
or filesystem context. TraceBench fragmentation is diagnostic only because its
event proxy is produced by a heuristic digit-removal regex rather than human
review. Neither corpus provides enough evidence to merge those shapes safely.

The public HDFS corpora do not cover application distinctions such as SQLSTATE,
HTTP status, service boundaries, inline peer entities, or errors hidden after a
long wrapper prefix. A small versioned controlled complement therefore tests
only those missing contracts. Its initial run found two generic defects:
fingerprints discarded meaningful tails after 180 characters, and inline
`peer=` values fragmented one socket error shape. Fingerprints now retain a
bounded head and tail and normalize explicit peer/host/node/pod entity fields
while keeping the original messages as evidence.

The controlled rerun passes 16/16 operational event labels with 100% pairwise
precision and recall, zero collisions, and zero fragmentation. This controlled
result is a contract test, not evidence of real-world prevalence or incident
accuracy.

A post-change deterministic HDFS v3 pipeline rerun retained 41 typed
observations instead of 38, all in fault-labeled cases. The three additional
observations are established storage-I/O observations. Candidate support
remains 3/8 failed and 0/8 normal cases; grounding and impact-contract gates
remain 100%, with zero unknown evidence IDs or raw identifier leaks. The
change therefore improved evidence retention without widening root-cause
eligibility.

### Curated real BGL and OpenStack pair gate

The next gate uses real BGL and OpenStack messages instead of adding more
synthetic incident scenarios. Candidate generation scans the complete local
corpora, selects the same label-blind BGL windows and OpenStack instances used
by the existing adapters, minimizes identifiers, hashes case/record references,
and exports unlabelled same-group variants and near-neighbor boundaries:

```bash
python scripts/generate_real_log_pair_candidates.py \
  --per-type 40 \
  --output output/real-log-pair-candidates.json

python scripts/evaluate_real_log_pairs.py \
  --output output/real-log-pair-benchmark.json
```

The generator inspected all 4,747,963 BGL lines and 207,820 OpenStack lines,
then emitted 95 candidate pairs from 3,782 selected BGL records and 300 selected
OpenStack records. Seventy-three unambiguous minimized pairs were manually
reviewed and versioned: 34 should share one event shape and 39 must remain
separate. Ambiguous register-index, optional-summary, and event-family/entity
questions are excluded rather than forced into the score. The review was
performed by the Codex agent, not an independent human reviewer, so this is a
curated contract boundary rather than a human gold-set accuracy claim.

The real pairs exposed defects that the controlled complement did not:

- natural language such as `Instance spawned successfully` was temporarily
  mistaken for an inline `instance=<id>` field; entity normalization now
  requires an explicit `=` or `:`;
- an OpenStack UUID followed by `_del` escaped a word-boundary-based
  minimization regex; UUID/hex minimization now uses hexadecimal lookarounds,
  and the regenerated candidate artifact passes an explicit UUID scan;
- prefixed hexadecimal values such as `0x0000df30` fragmented one BGL register
  event shape;
- a long decimal count such as `10422649` was mistaken for unprefixed hex;
  unprefixed hex now requires at least one `a-f` character; and
- the same OpenStack event split when its leading request envelope was
  `[req-...]` in one source and `[-]` in another. Only that leading envelope is
  normalized; the operation text remains intact.

After those corrections the real-pair benchmark passes 73/73:

| Measure | Result |
| --- | ---: |
| Same-pair precision | 100% |
| Same-pair recall | 100% |
| Different-pair specificity | 100% |
| Over-merged pairs | 0 |
| Fragmented pairs | 0 |
| Raw UUID matches in candidate artifact | 0 |

The broader post-change dataset regressions also pass. BGL retains the same
case coverage and one supported alert case while collapsing 160 observations
to 146 by removing false value-based fragmentation; 145/146 remain
observation-only. OpenStack retains four peer-relative latency observations in
the four anomaly-labelled cases, zero supported causes, and zero observations
in the eight selected normal cases. Both datasets retain 100% grounding and
impact-contract pass rates with zero unknown evidence IDs, unsafe baselines, or
raw identifier leaks.

The full repository regression suite now passes 183/183 tests.

### Spark 2k pre-LLM pilot

The next dataset case uses the official LogHub Spark 2k raw and structured
samples. It is deliberately split into a data-quality gate and a deterministic
incident-analysis gate:

```bash
python scripts/evaluate_spark_pilot.py \
  --sample-limit 200
```

The adapter parses the raw text without source labels, assumes UTC only for
source-relative ordering, and minimizes IP addresses, UUIDs, application IDs,
executor host IDs, user-cache names, HDFS user roots, and ACL user sets.
`EventId` is retained separately as evaluation truth and joined only after
normalization and inferred grouping are complete.

The first label-last run had 100% pairwise precision but only 85.07% recall.
The dominant fragmentation was not a Spark-specific label exception: identical
measurement-bearing messages split when display units changed between B and KB,
and signed timing values split from positive timing values. The production
fingerprint now treats a numeric measurement plus its display unit as one
volatile value and normalizes the sign of generic volatile numbers. Semantic
codes such as HTTP status, SQLSTATE, and explicit error codes remain protected.

The final Spark results are:

| Measure | Result |
| --- | ---: |
| Raw parser coverage | 100% (2,000/2,000) |
| Raw/structured adapter equivalence | 100% |
| Sampled source-template coverage | 100% (36/36 in 200 rows) |
| Rare source-template coverage | 100% |
| Pairwise precision | 100% |
| Pairwise recall | 98.91% |
| Pairwise F1 | 99.45% |
| Cross-template collision groups | 0 |
| Deterministic 40-pair review sample | 40/40 |

One upstream template remains split into two conservative inferred shapes:
Spark's broad `Block <*> stored as bytes in memory` template covers both RDD
blocks and broadcast blocks. Keeping those object families separate preserves
useful operational meaning and does not create an over-merge. The quality gate
therefore passes without adding an EventId-specific rule.

All 2,000 source rows are INFO. The full deterministic pre-review pipeline
correctly produces zero observations, zero cause candidates, valid grounding,
and an `abstained` review with the reason `no deterministic candidate has
supporting evidence`. No OpenAI request is made. The HTML label was also changed
from `Evidence Pack Sent To LLM` to `Evidence Pack Prepared For Interpretation`
so an offline deterministic review does not claim a model call that never
happened.

This pilot validates Spark parsing, minimization, thinning, grouping, evidence
pack construction, and honest abstention. It does **not** validate Spark failure
recall, incident causality, or root-cause accuracy. The next useful input is a
failure-rich Spark case containing an executor loss, block-fetch failure, or
job/stage failure with enough ordered context to evaluate signal and impact.
Only after that case passes should Spark evidence be sent to OpenAI.

The full repository regression suite now passes 191/191 tests.

### Scope decision after the Spark pilot

Spark's adapter/grouping/abstention boundary is complete, but Spark is not a
confirmed workload in the target environment. Further Spark-specific fault
cases are therefore parked rather than allowed to steer the core pipeline.
Public Hadoop, HDFS, BGL and OpenStack results remain useful generalization
evidence, not a product support declaration. The next dataset must be selected
from the real application, runtime and observability profile documented in
`TARGET_ENVIRONMENT_AND_DATA_PRIORITY.md`; Kafka and Kubernetes data are also
conditional on that profile.
