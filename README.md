# Incident Agent

Incident Agent turns an alert into a reviewable incident analysis.

It collects a limited amount of evidence, ranks possible explanations and
shows uncertainty. A human reviews the result. The agent does not remediate
systems or publish reports by itself.

## How a result is produced

```text
alert
  -> validate, normalize and redact
  -> collect bounded logs, metrics and deployment evidence
  -> extract deterministic signals
  -> rank explanations (optional model interpretation)
  -> freeze the analysis for human review
```

MySQL stores alerts, queued work, evidence, analysis revisions and review
decisions. Two workers process the queue. LangGraph checkpoints each step so a
different worker can continue after a crash.

The model receives only bounded, redacted evidence. It can explain or abstain,
but it cannot create evidence, approve a result, publish or take operational
action.

## How the reported results were obtained

This project does not train or fine-tune a model. It evaluates the complete
analysis pipeline:

1. Start with synthetic fixtures or public raw logs.
2. Normalize and redact them without access to the expected answer.
3. Build evidence and candidate explanations using deterministic contracts.
4. Optionally ask the model to interpret the bounded evidence.
5. Freeze the output.
6. Join the held-out labels only after the output is frozen.
7. Score grounding, grouping and safe abstention.

Labels and fault metadata are never inserted into alerts, rules, prompts or
model requests. A weak result becomes a regression test or a general contract
improvement; dataset-specific answers are not added as hidden rules.

Current checked results:

| Check | Result | What it measures |
| --- | --- | --- |
| Engineering gate | 349 tests; 75.4% repository, 82.2% core and 95.9% security branch coverage | Code and runtime behavior |
| HDFS 2k grouping | 100% pair precision, 96.60% recall | Log grouping on one public corpus |
| HDFS v3/TraceBench grouping | 100% pair precision, 98.83% recall | Grouping on a second corpus |
| Spark 2k grouping | 100% precision, 98.91% recall, 99.45% F1 | Parsing and grouping, not root-cause accuracy |
| Hadoop pre-review | 55/55 grounded; 0 unknown evidence IDs; 98.18% exact result or honest abstention | Evidence and abstention boundary |
| Live model evaluation, 2026-08-09 | 22 successful bounded calls; 0 unknown evidence IDs or unsupported percentages | Model transport and grounded output on limited cases |
| Local load run, 2026-08-24 | 100,000 synthetic events; 12 revisions; 12 model calls; 0 dead letters | Bucketing, queueing and budget fallback, not production capacity |

These are separate checks, not one “AI accuracy” score. Full methods and
limitations:

- [Pre-review evaluation](docs/reports/PRE_REVIEW_EVALUATION.md)
- [Live model evaluation](docs/reports/OPENAI_LIVE_EVALUATION_2026-08-09.md)

Reproduce the main checks:

```bash
.venv/bin/python scripts/quality_gate.py
.venv/bin/python scripts/evaluate_pre_review.py
.venv/bin/python scripts/evaluate_hadoop_typed_review.py --cases 55 \
  --output output/hadoop-typed-review-all-55.json
```

## Run locally

Requirements: Docker Compose v2, 4 GB free memory and free ports `8000`,
`3307`, `9101` and `9102`.

Run the full local pipeline without external model calls:

```bash
docker compose up --build --wait
docker compose --profile tools run --rm --no-deps verify
```

Open the review UI at <http://127.0.0.1:8000/>. Local credentials are
`incident-reviewer` / `local-review-only`.

To include OpenAI, put `OPENAI_API_KEY`, `OPENAI_BASE_URL` and `OPENAI_MODEL`
in `.env`, then run:

```bash
docker compose -f compose.yaml -f compose.openai.yaml up --build --wait
docker compose -f compose.yaml -f compose.openai.yaml --profile tools run --rm --no-deps verify
```

External publication remains disabled. The OpenAI run sends only redacted
synthetic evidence.

Useful endpoints:

- review: <http://127.0.0.1:8000/>
- API docs: <http://127.0.0.1:8000/docs>
- readiness: <http://127.0.0.1:8000/readyz>
- metrics: <http://127.0.0.1:8000/metrics>

For setup, recovery, stress tests and reset commands, use the
[Docker Compose runbook](docs/operations/LOCAL_DOCKER_COMPOSE.md).

## Main code

| Path | Purpose |
| --- | --- |
| `webhook/` | API, durable queue and review lifecycle |
| `graph/` | LangGraph workflow and checkpoints |
| `clients/` | Evidence-source and model adapters |
| `utils/`, `rules/` | Redaction, evidence, correlation, budgets and safety |
| `fixtures/`, `evaluation/` | Evaluation data loaders and scoring |
| `tests/`, `scripts/` | Tests, verification and operational tools |
| `docs/` | Architecture, contracts, operations and full reports |

Start with [the documentation index](docs/README.md) for anything beyond this
overview.

## Safety boundary

- Human approval is required.
- Automatic remediation is not implemented.
- External publishing is off by default.
- Model confidence is not proof of causality.
- Missing or contradictory evidence can produce an explicit abstention.
- Local test results are not a production-readiness claim.

Production requirements and the release gate are in
[PRODUCTION_READINESS.md](docs/operations/PRODUCTION_READINESS.md).
