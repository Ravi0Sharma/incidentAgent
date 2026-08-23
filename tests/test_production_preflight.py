"""Production preflight combines configuration, HA, schema and PITR gates."""

import unittest
from unittest.mock import patch

from scripts import production_preflight


class ProductionPreflightTests(unittest.TestCase):
    def test_non_secure_environment_cannot_claim_a_production_preflight(self):
        with patch.object(production_preflight.settings, "ENVIRONMENT", "development"):
            with self.assertRaisesRegex(RuntimeError, "shadow or production"):
                production_preflight.run_preflight()

    def test_preflight_requires_two_workers_current_schema_and_pitr(self):
        dependencies = {
            "database": "ready",
            "queue": "ready",
            "schema": "ready",
            "worker": {"status": "ready", "active_workers": 2},
        }
        with (
            patch.object(production_preflight.settings, "ENVIRONMENT", "shadow"),
            patch.object(production_preflight.settings, "MIN_ACTIVE_WORKERS", 2),
            patch.object(
                production_preflight.settings,
                "WORKER_HEARTBEAT_STALE_SECONDS",
                15,
            ),
            patch.object(production_preflight, "validate_runtime_config"),
            patch.object(
                production_preflight,
                "readiness_check",
                return_value=dependencies,
            ) as readiness,
            patch.object(
                production_preflight,
                "check_pitr_readiness",
                return_value={"status": "passed"},
            ),
        ):
            report = production_preflight.run_preflight()

        self.assertEqual(report["configuration"], "passed")
        self.assertEqual(readiness.call_args.kwargs["minimum_workers"], 2)
