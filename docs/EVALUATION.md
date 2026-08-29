# Evaluation

This document explains how the public results are produced and what they do
and do not establish. Incident Agent does not train or fine-tune a foundation
model.

## Method

The evaluation is label-last:

1. Load a synthetic fixture or public raw-log corpus.
2. Normalize, redact and group records without the expected answer.
3. Extract deterministic signals, impact links and candidate explanations.
4. Optionally run bounded model interpretation against the evidence pack.
5. Validate structured output, citations and claim roles.
6. Freeze the analysis and review artifact.
7. Join held-out labels or fault metadata.
8. Score grouping, grounding, supported answers and safe abstention.

Ground truth is never added to alerts, rules, candidate scoring, prompts or
model requests. A failing case becomes a regression test or a general contract
improvement; a dataset-specific answer is not added as a hidden rule.

## Evaluation layers

| Layer | Input | Question answered |
| --- | --- | --- |
| Unit and contract tests | Synthetic boundary cases | Does code enforce its declared contracts? |
| Public-log grouping | HDFS, BGL, OpenStack and Spark logs | Does normalization preserve event shapes without excessive merging? |
| Label-last review | Hadoop/HDFS/OpenStack cases | Are claims grounded, and does the system abstain when evidence is insufficient? |
| Live model check | Small bounded synthetic/public cases | Does provider transport and structured grounding work? |
| Admission load | Synthetic signed alerts | Do bucketing, queueing and model budgets bound work? |
| Recovery tests | MySQL plus independent processes | Can leased work and checkpoints survive process loss without duplicate revisions? |

## Checked baseline

| Check | Result | Scope |
| --- | --- | --- |
| Engineering gate | 352 tests; 75.4% repository, 82.2% core and 95.9% security branch coverage | Code and local runtime behavior |
| HDFS 2k grouping | 100% pair precision; 96.60% recall; 14/14 templates retained | One public grouping corpus |
| HDFS v3/TraceBench grouping | 100% pair precision; 98.83% recall; 75/75 labels retained | A second public grouping corpus |
| Curated BGL/OpenStack pairs | 73/73; 100% precision, recall and specificity | Reviewed normalization boundary, not an independent gold set |
| Spark 2k grouping | 2,000/2,000 parsed; 100% precision; 98.91% recall; 99.45% F1 | INFO-only parsing and grouping |
| Larger public-data audit | 575,061 HDFS traces and 207,820 primary OpenStack events processed label-last | Signal retention and impact boundaries |
| Hadoop pre-review | 55/55 grounded; 0 unknown evidence IDs; 0 unsupported predictions; 54/55 exact result or honest abstention | Evidence and abstention boundary |
| Live model check | 22 successful bounded calls; 0 unknown evidence IDs or unsupported percentages | Limited provider/structured-output check |
| Local admission load | 100,000 synthetic events; 12 revisions; 12 model calls; 0 dead letters | Bucketing, queueing and deterministic fallback |

These rows are separate checks, not one model-accuracy score:

- Code coverage does not measure incident correctness.
- Grouping precision and recall do not measure root-cause accuracy.
- Grounding proves that a claim cites known compatible evidence; it does not
  prove causality.
- The Hadoop 54/55 measure accepts an honest abstention. Raw exact agreement
  was lower because several supplied labels were absent from or conflicted
  with recoverable evidence.
- The live model sample is too small to establish provider reliability,
  calibration or production quality.
- The admission run is synthetic local evidence, not a capacity, SLO or cost
  benchmark.

## High-volume result

Matching alerts share a five-minute incident bucket. Every distinct event is
stored, while each bucket retains one pending analysis job and at most one
follow-up during active work.

The 100,000-event run produced 12 durable analysis revisions and 12 successful
model calls. The incident call budget then blocked six later provider calls
and used deterministic fallback. No job entered the dead-letter queue. This
tests admission and budget behavior, not production throughput.

## CloudWatch verification boundary

The CloudWatch implementation constructs real boto3 clients for Logs Insights
and GetMetricData. Public tests inject sanitized AWS-shaped fake clients and
verify fixed allowlisted queries, polling, pagination, truncation, partial
results, error mapping and provenance.

No AWS account identifiers, credentials, private source map or raw telemetry
are included. The repository does not contain evidence of a completed call
against a real AWS account, and the EventBridge translator is not yet wired to
the HTTP intake route. See the [CloudWatch guide](operations/CLOUDWATCH.md).

## Reproduce

Install the locked development dependencies, then run:

```bash
.venv/bin/python scripts/quality_gate.py
.venv/bin/python scripts/evaluate_pre_review.py
.venv/bin/python scripts/evaluate_hadoop_typed_review.py --cases 55 \
  --output output/hadoop-typed-review-all-55.json
```

Focused checks:

```bash
.venv/bin/python -m unittest tests.test_cloudwatch_connector
.venv/bin/python -m unittest tests.test_distributed_runtime
.venv/bin/python scripts/check_repository_secrets.py
.venv/bin/python scripts/check_markdown_links.py
```

Generated JSON/HTML remains under ignored `output/`. Public raw datasets are
also ignored; their allowlist, source URLs and fetch procedure are documented
in [data/external/README.md](../data/external/README.md).

## Before a production claim

A production evaluation needs representative approved incidents, independently
adjudicated responder truth, a read-only shadow period, target-environment
latency/recovery evidence, provider cost reconciliation and explicit quality
thresholds. The required gates are in
[PRODUCTION_READINESS.md](operations/PRODUCTION_READINESS.md).
