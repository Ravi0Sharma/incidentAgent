# LogHub 2.0 intake and first parser audit — 2026-08-09

## Scope

LogHub 2.0 was downloaded from the official
[Zenodo record](https://zenodo.org/records/8275861). All fourteen split ZIP
archives are stored under `data/loghub-2.0/archives`; every archive passed both
its published MD5 checksum and `unzip` integrity validation.

This corpus is used as label-last evaluation data. Its `EventId` and
`EventTemplate` fields are parsing/template truth, not incident, impact, or
root-cause truth. They must never be exposed to the incident pipeline before
inference.

## Local data state

The five first-priority datasets are unpacked under
`data/loghub-2.0/extracted/<dataset>/<dataset>`:

| Dataset | Raw lines | Template labels | Initial purpose |
| --- | ---: | ---: | --- |
| HDFS | 11,167,740 | 46 | parser and grouping generalization |
| Spark | 16,075,117 | 236 | multiline/error retention and grouping |
| OpenStack | 207,632 | 48 | infrastructure parser regression |
| ZooKeeper | 74,273 | 89 | nested-thread parser and temporal windows |
| Linux | 23,921 | 338 | later cloud-host/syslog adapter work |

The verified archives occupy about 964 MB and the five extracted datasets
about 6.4 GB. The other nine archives remain compressed until a concrete test
requires them.

## First full raw-format audit

Before changing code, exact top-level format matching produced:

| Dataset | Recognized rows | Physical rows | Result |
| --- | ---: | ---: | --- |
| HDFS | 11,167,740 | 11,167,740 | complete |
| Spark | 16,074,617 | 16,075,117 | 500 untimed exception rows exposed |
| OpenStack | 207,632 | 207,632 | complete |
| ZooKeeper | 68,691 | 74,273 | 5,582 valid nested-thread rows exposed |
| Linux | 23,921 | 23,921 | raw format recognized; no product adapter claim |

The two misses were general parser weaknesses, not source-label failures:

- Spark includes 500 exception records without their own timestamp. The raw
  adapter now retains them as error events, uses the previous event time only
  for source-relative ordering, and declares
  `timestamp_quality=inferred_from_previous_event`.
- ZooKeeper thread fields can contain nested brackets and IPv6-like colon
  sequences. The parser now locates the final `component@line` suffix rather
  than misclassifying those events as continuations.

After the fixes, Spark accounts for all 16,075,117 physical rows as 16,074,617
timestamped records plus 500 explicitly untimed exception records. ZooKeeper's
real adapter parses 74,273/74,273 records, with no false continuation rows in
this corpus. Both behaviors have focused regression tests.

## What this proves and does not prove

It proves archive integrity, raw parser compatibility, explicit handling of
missing timestamps, and one real cross-corpus generalization improvement. It
does not prove incident detection, correlation, RCA accuracy, or production
support for these technologies.

The next bounded test is template-label-last thinning/grouping on failure-rich
Spark and ZooKeeper windows. Only the resulting evidence packs—not millions of
raw rows—should be eligible for an OpenAI evaluation. Railway remains later;
hosting cannot improve parser or evidence quality.

## Bounded grouping and OpenAI abstention gate — 2026-08-10

The follow-up scanned all 16,075,117 Spark rows without template labels and
found 17,473 signal-bearing rows across 147 inferred fingerprints. Six
non-overlapping 81-line windows were chosen deterministically. Template truth
was read separately and joined only after grouping. ZooKeeper used three
label-free ten-minute windows selected by the same pre-existing adapter.

| Dataset | Evaluated rows | Template labels | Precision | Recall | Grounding |
| --- | ---: | ---: | ---: | ---: | ---: |
| Spark | 486 | 71 | 1.0000 | 0.9764 | 6/6 |
| ZooKeeper | 90 | 2 | 1.0000 | 1.0000 | 3/3 |

Spark produced no cross-template collisions. Its 110 false-negative pairs came
from twelve templates split into at most two inferred groups. The examples are
mostly defensible operational distinctions that LogHub's parser templates
merge, such as master versus worker hosts and different service names. No
pipeline rule was weakened to imitate the source labels.

All nine deterministic reviews abstained. Five Spark windows retained direct
`unclassified_error` observations but had no adverse lifecycle/impact link.
The ZooKeeper windows contained repeated channel-open warnings but no supported
impact evidence. A ZooKeeper-specific causal rule was deliberately not added;
the target environment has not established ZooKeeper as supported scope.

Two minimized evidence packs were then sent to the configured official OpenAI
Responses endpoint with structured output and `store=False`:

- 2/2 provider successes;
- 2/2 expected `abstained` status boundaries;
- 2/2 grounding passes;
- zero hypotheses, unknown evidence IDs, or unsupported percentages;
- 4,030 input tokens and 710 output tokens in 8.557 seconds.

The model reported only observed Spark errors or ZooKeeper warnings, explicitly
said that impact and causality were not established, and suggested read-only
evidence collection. The provider result is in
`output/loghub2-openai-2026-08-10.json`; standalone reviews are in
`output/loghub2-openai-2026-08-10/`.

Review also exposed a provenance-key mismatch: Spark adapters wrote
`ordering=source_relative`, while canonical normalization consumes
`timestamp_ordering_scope`. Both Spark adapters now use the canonical key, so
inferred timestamps cannot be presented as globally ordered. A regression test
locks this behavior.

At that stage the full local quality gate passed 281/281 tests. The later Linux
run below raised the documented count to 284/284; coverage remained 74.8%
whole-repository, 82.4% core, and 97.2% security.

## Linux/syslog parser and privacy gate — 2026-08-10

The full LogHub 2.0 Linux corpus now runs through a label-last syslog parser
and grouping evaluation. All 23,921 physical rows parse successfully and all
338 source template labels are held out until after inference.

The source omits both year and severity. The adapter therefore preserves
`level=unknown`, records `timestamp_quality=year_missing`, and marks all rows
`timestamp_ordering_scope=not_comparable`. It is intentionally **not eligible**
for timeline correlation, impact/RCA evaluation, or OpenAI interpretation.

Initial grouping recall was 0.6541. Review exposed a general issue rather than
a Linux-specific parser rule: auth/syslog messages contained keyed user,
remote-host, and reverse-DNS values, and messages embedded volatile human
timestamps. The common redaction and fingerprinting layers now redact those
identity values and normalize embedded timestamps. The repeat run achieved
0.7831 recall at 0.999999 precision.

The remaining fragmentation is mostly meaningful: audit/SELinux records differ
in syscall, resource, permission or process, and startup/shutdown records name
different daemons. We retain those distinctions rather than weaken grouping to
match a broad source template. The result is
`output/loghub2-linux-2026-08-10.json`.

The quality gate then passed 284/284 tests; coverage remained 74.8% overall,
82.4% core, and 97.2% security.
