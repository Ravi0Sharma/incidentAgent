import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.config_versions import config_version_manifest


class ConfigVersionTests(unittest.TestCase):
    def test_manifest_is_stable_and_contains_every_pipeline_component(self):
        first = config_version_manifest()
        second = config_version_manifest()
        self.assertEqual(first, second)
        self.assertEqual(first["schema_version"], "pipeline-config-manifest/v1")
        self.assertEqual(
            set(first["components"]),
            {
                "detection_rules", "normalization", "suppressions",
                "code_map", "service_registry", "cloudwatch_source_map",
                "telemetry_route", "incident_bucketing", "evidence_pack",
            },
        )
        self.assertTrue(first["manifest_sha256"].startswith("sha256:"))
        self.assertTrue(all(first["components"].values()))

    def test_changed_configuration_changes_only_its_component_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "code_map.yaml"
            path.write_text("codes: {}\n")
            with patch.dict(os.environ, {"CODE_MAP_PATH": str(path)}):
                first = config_version_manifest()
                path.write_text("codes:\n  HTTP:\n    '500': server_error\n")
                second = config_version_manifest()
        self.assertNotEqual(
            first["components"]["code_map"],
            second["components"]["code_map"],
        )
        self.assertNotEqual(first["manifest_sha256"], second["manifest_sha256"])
        for key in set(first["components"]) - {"code_map"}:
            self.assertEqual(first["components"][key], second["components"][key])

    def test_incident_bucketing_is_content_addressed(self):
        with patch.dict(
            os.environ,
            {
                "INCIDENT_BUCKET_SECONDS": "300",
                "INCIDENT_COALESCE_SECONDS": "5",
                "INCIDENT_COALESCE_MAX_SECONDS": "30",
            },
        ):
            first = config_version_manifest()
        with patch.dict(
            os.environ,
            {
                "INCIDENT_BUCKET_SECONDS": "600",
                "INCIDENT_COALESCE_SECONDS": "10",
                "INCIDENT_COALESCE_MAX_SECONDS": "60",
            },
        ):
            second = config_version_manifest()
        self.assertNotEqual(
            first["components"]["incident_bucketing"],
            second["components"]["incident_bucketing"],
        )
        self.assertNotEqual(first["manifest_sha256"], second["manifest_sha256"])

    def test_cloudwatch_source_map_and_route_are_content_addressed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cloudwatch.yaml"
            path.write_text("version: cloudwatch-source-map/v1\nservices: {}\n")
            environment = {
                "CLOUDWATCH_SOURCE_MAP_PATH": str(path),
                "CLOUDWATCH_REGION": "eu-north-1",
                "LOG_SOURCE": "cloudwatch",
                "METRIC_SOURCE": "cloudwatch",
            }
            with patch.dict(os.environ, environment):
                first = config_version_manifest()
                path.write_text(
                    "version: cloudwatch-source-map/v1\n"
                    "services:\n  checkout:\n    log_groups: []\n"
                )
                second = config_version_manifest()
        self.assertNotEqual(
            first["components"]["cloudwatch_source_map"],
            second["components"]["cloudwatch_source_map"],
        )
        self.assertEqual(
            first["components"]["telemetry_route"],
            second["components"]["telemetry_route"],
        )
        self.assertNotEqual(first["manifest_sha256"], second["manifest_sha256"])
