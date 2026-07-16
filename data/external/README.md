# External evaluation data

Raw public datasets and generated derivatives are intentionally not committed.
The allowlist and source URLs live in
`config/public_log_datasets.yaml`.

## Fetch the selected small corpus

```bash
python scripts/fetch_public_logs.py \
  --dataset loghub_hdfs_2k \
  --accept-research-license

python scripts/fetch_public_logs.py \
  --dataset loghub_spark_2k \
  --accept-research-license
```

The command writes the source CSV, upstream README/license, and a
`download_receipt.json` containing source URLs, byte sizes, SHA-256 digests,
and retrieval time under `data/external/raw/`.

## Evaluate it

```bash
python scripts/evaluate_public_logs.py \
  --dataset loghub_hdfs_2k
```

This is a robustness corpus, not an incident gold set. It can test whether the
pipeline parses timestamps, keeps representative signals, avoids accidental
over-grouping, and behaves deterministically. It cannot establish root-cause
accuracy because it has no reviewed incident timeline, deploy/metric context,
or causal labels.
