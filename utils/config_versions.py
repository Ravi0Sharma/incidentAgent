"""Content-addressed versions for pipeline configuration and rules."""

import hashlib
import json
import os
from pathlib import Path


PIPELINE_CONFIG_MANIFEST_VERSION = "pipeline-config-manifest/v1"
_ROOT = Path(__file__).resolve().parent.parent


def _digest_file(path):
    candidate = Path(path)
    if not candidate.is_file():
        return None
    return "sha256:" + hashlib.sha256(candidate.read_bytes()).hexdigest()


def _digest_directory(path):
    directory = Path(path)
    if not directory.is_dir():
        return None
    digest = hashlib.sha256()
    matched = False
    for candidate in sorted(directory.iterdir(), key=lambda item: item.name):
        if not candidate.is_file() or candidate.suffix.lower() not in {".md", ".yaml", ".yml"}:
            continue
        matched = True
        digest.update(candidate.name.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(candidate.read_bytes()).digest())
    return "sha256:" + digest.hexdigest() if matched else None


def _digest_object(value):
    serialized = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(serialized).hexdigest()


def config_version_manifest():
    """Return stable hashes without persisting local paths or file contents."""
    components = {
        "detection_rules": _digest_directory(
            os.getenv("DETECTION_RULES_DIR", _ROOT / "rules")
        ),
        "normalization": _digest_file(
            os.getenv("LOG_SCHEMAS_PATH", _ROOT / "config" / "log_schemas.yaml")
        ),
        "suppressions": _digest_file(
            os.getenv("SUPPRESSIONS_PATH", _ROOT / "config" / "suppressions.yaml")
        ),
        "code_map": _digest_file(
            os.getenv("CODE_MAP_PATH", _ROOT / "config" / "code_map.yaml")
        ),
        "service_registry": _digest_file(
            os.getenv("SERVICES_CONFIG_PATH", _ROOT / "config" / "services.yaml")
        ),
        "cloudwatch_source_map": (
            _digest_file(os.getenv("CLOUDWATCH_SOURCE_MAP_PATH"))
            if os.getenv("CLOUDWATCH_SOURCE_MAP_PATH")
            else "disabled"
        ),
        "telemetry_route": _digest_object({
            "log_source": os.getenv("LOG_SOURCE", "loki").strip().lower(),
            "metric_source": os.getenv("METRIC_SOURCE", "prometheus").strip().lower(),
            "cloudwatch_region": os.getenv("CLOUDWATCH_REGION", "").strip(),
        }),
        "incident_bucketing": _digest_object({
            "bucket_seconds": int(
                os.getenv("INCIDENT_BUCKET_SECONDS", "300")
            ),
            "coalesce_seconds": float(
                os.getenv("INCIDENT_COALESCE_SECONDS", "0")
            ),
            "coalesce_max_seconds": float(
                os.getenv("INCIDENT_COALESCE_MAX_SECONDS", "30")
            ),
        }),
        "evidence_pack": "evidence-pack/v3",
    }
    serialized = json.dumps(
        components, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "schema_version": PIPELINE_CONFIG_MANIFEST_VERSION,
        "manifest_sha256": "sha256:" + hashlib.sha256(serialized).hexdigest(),
        "components": components,
    }
