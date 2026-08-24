# OpenAI live evaluation – 2026-08-09

Status: **local live-eval complete; not a production or hosted-release claim**

The model was `gpt-5.6-luna` through the official OpenAI Responses API. Every
request used `store=false`; dataset truth was joined only after the model
boundary, and external publishing remained disabled.

## Results

| Evaluation | Provider | Boundary/diagnostic result | Grounding |
| --- | ---: | --- | ---: |
| One-case Hadoop smoke | 1/1 | Correct `normal` | 1/1 |
| Balanced Hadoop portfolio | 8/8 | Diagnostic gate passed | 8/8 |
| HDFS v3/BGL/ZooKeeper portfolio | 7/7 | 7/7 expected supported/abstained | 7/7 |
| Full HDFS v3 pre-review E2E | 5/5 model calls | `supported` + `abstained` | 2/2 cases |
| Focused Hadoop contract recheck | 1/1 | Contract and diagnostic gates passed | 1/1 |

Across the new LogHub portfolio there were zero unknown evidence IDs and zero
unsupported percentages. The full pre-review run executed ingest,
normalization, grouping, detections, features, correlation, severity,
candidate scoring, evidence packing, bounded semantic investigation,
interpretation, grounding and review rendering. It made four bounded semantic
tool calls and produced one supported hypothesis plus one honest abstention.

## Finding and correction

The first balanced Hadoop report rejected one otherwise visible
`observation-pattern-*` citation. The evidence pack showed that derived pattern
to the model, but the Hadoop-specific validator allowlisted only log,
detection, evidence-graph and anchor IDs. `evaluation/hadoop_llm.py` now also
collects pattern IDs from `deterministic_assessment.observation_patterns`.

A regression test covers the contract, and the exact previously failing
network case was rerun. It passed citation validation, claim validation,
contract gate and diagnostic gate with no unsupported IDs. The full locked
suite subsequently passed 284/284 tests.

## Data-ceiling interpretation

The balanced Hadoop report's raw exact accuracy must not be treated as product
accuracy. Three labeled abnormal applications had no recoverable matching
failure signal even in their available raw records, and one case contained
competing direct machine/network observations. These are recorded as
data-ceiling or label/evidence conflicts. The pipeline was not changed to infer
the hidden label; the diagnostic gate instead rewards a supported answer or
honest abstention.

## Usage and cost

All live runs in this batch used 47,846 input tokens and 8,846 output tokens
across 22 successful provider calls. At the official `gpt-5.6-luna` list price
verified on 2026-08-09 ($0.20/input MTok and $1.20/output MTok), estimated model
cost was approximately **$0.0202** in total. The full two-case pre-review E2E
used 12,084 tokens and cost approximately **$0.0046**.

The application ledger correctly reports `pricing_not_configured` because the
local `.env` leaves currency enforcement disabled. Before any hosted runtime,
configure:

- `LLM_INPUT_USD_PER_MILLION_TOKENS`
- `LLM_OUTPUT_USD_PER_MILLION_TOKENS`
- a positive `LLM_MAX_COST_USD_PER_INCIDENT`

Source for model availability and list price:
<https://developers.openai.com/api/docs/models>.

## Artifacts

- `output/hadoop-openai-live-smoke-2026-08-09.json` and `.html`
- `output/hadoop-openai-balanced-8-2026-08-09.json` and `.html`
- `output/hadoop-openai-contract-recheck-2026-08-09.json` and `.html`
- `output/new-loghub-openai-live-2026-08-09.json`
- `output/new-loghub-openai-live-2026-08-09/index.html` plus seven case reviews
- `output/full-pre-review-openai-live-2026-08-09.json`
- `output/full-pre-review-openai-live-2026-08-09/index.html` plus two reviews

## Hosted deployment gate

The local AI/data/review path is ready for a deployment-preparation phase, but
not for an unbounded public deployment. Hosted deployment work may start only after a
cost cap is selected and the already parked hosting inputs are available:
runtime environment, managed MySQL, secrets, health/readiness configuration
and review authentication. GitHub automation is not required for another local
eval, but remains required before describing the deployment process as a
reproducible production release.
