"""Fetch an allowlisted public log corpus with a local provenance receipt."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import sys
from urllib.request import Request, urlopen

import yaml


_HERE = os.path.dirname(
    os.path.abspath(__file__)
)
_ROOT = os.path.dirname(_HERE)
_CONFIG = os.path.join(
    _ROOT,
    "config",
    "public_log_datasets.yaml",
)


def _load_config():
    with open(
        _CONFIG,
        encoding="utf-8",
    ) as handle:
        return yaml.safe_load(handle)


def _download(url, path):
    request = Request(
        url,
        headers={
            "User-Agent":
            "incident-agent-public-eval/1.0"
        },
    )
    with urlopen(
        request,
        timeout=30,
    ) as response:
        content = response.read()
    os.makedirs(
        os.path.dirname(path),
        exist_ok=True,
    )
    with open(path, "wb") as handle:
        handle.write(content)
    return {
        "source_url": url,
        "local_file": os.path.basename(
            path
        ),
        "bytes": len(content),
        "sha256": hashlib.sha256(
            content
        ).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        choices=[
            "loghub_hdfs_2k",
            "loghub_spark_2k",
        ],
        required=True,
    )
    parser.add_argument(
        "--accept-research-license",
        action="store_true",
        help=(
            "Confirm the upstream research/"
            "academic usage terms."
        ),
    )
    args = parser.parse_args()
    if not args.accept_research_license:
        parser.error(
            "--accept-research-license is "
            "required"
        )

    config = _load_config()
    dataset = config["datasets"][
        args.dataset
    ]
    target = os.path.join(
        _ROOT,
        os.path.dirname(
            dataset["local_path"]
        ),
    )
    configured_files = [
        ("raw_log_url", "Spark_2k.log"),
        (
            "structured_log_url",
            os.path.basename(
                dataset["local_path"]
            ),
        ),
        (
            "template_url",
            "Spark_2k.log_templates.csv",
        ),
        (
            "upstream_readme_url",
            "UPSTREAM_README.md",
        ),
        (
            "upstream_license_url",
            "UPSTREAM_LICENSE",
        ),
    ]
    files = [
        (dataset[key], filename)
        for key, filename in configured_files
        if dataset.get(key)
    ]
    receipts = [
        _download(
            url,
            os.path.join(target, name),
        )
        for url, name in files
    ]
    receipt = {
        "dataset": args.dataset,
        "retrieved_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "intended_use": dataset[
            "intended_use"
        ],
        "prohibited_claims": dataset[
            "prohibited_claims"
        ],
        "upstream_terms_accepted": True,
        "files": receipts,
    }
    receipt_path = os.path.join(
        target,
        "download_receipt.json",
    )
    with open(
        receipt_path,
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            receipt,
            handle,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")
    print(json.dumps(
        receipt,
        indent=2,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
