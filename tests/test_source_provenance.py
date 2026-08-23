import json
import unittest
from unittest.mock import patch

from graph.nodes import (
    gather_deploys as gather_deploys_module,
    gather_logs as gather_logs_module,
    gather_metrics as gather_metrics_module,
)
from graph.nodes.aggregate_by_labels import (
    aggregate_by_labels,
)
from graph.nodes.gather_logs import (
    gather_logs,
)
from graph.nodes.gather_deploys import (
    gather_deploys,
)
from graph.nodes.gather_metrics import (
    gather_metrics,
)
from graph.nodes.correlate import (
    correlate,
)
from graph.nodes.normalize_logs import (
    normalize_logs,
)
from utils.connector_result import (
    CONNECTOR_PROVENANCE_VERSION,
    QUERY_SPEC_VERSION,
    provenance,
    query_spec,
)
from utils.evidence_pack import (
    build_evidence_pack,
)
from utils.html_report import (
    render_review,
)


class _MixedQualityLoki:
    base_url = (
        "https://user:password@"
        "loki.example.test/private"
        "?token=secret"
    )
    sampling_strategy = (
        "test_representative"
    )

    def get_log_stats(
        self, *args, **kwargs
    ):
        return {
            "total_count": 4,
            "count_is_exact": True,
        }

    def query_logs(
        self, *args, **kwargs
    ):
        valid = {
            "timestamp":
            "2026-07-28T12:00:00+02:00",
            "message":
            "connection refused token=raw-connector-secret",
            "labels": {
                "level": "warning",
            },
        }
        return [
            valid,
            dict(valid),
            {
                "timestamp":
                "not-a-timestamp",
                "message": "broken clock",
                "labels": {},
            },
            {
                "timestamp":
                "2026-07-28T10:00:01Z",
                "labels": {},
            },
        ]


class _MetricSource:
    base_url = (
        "https://prom.example.test/"
        "private?token=secret"
    )

    def query_metrics(
        self, *args, **kwargs
    ):
        metric = {
            "metric": "error_rate",
            "query":
            "secret raw promql",
            "value": 0.2,
            "timestamp":
            "2026-07-28T12:04:00+02:00",
        }
        return [
            metric,
            dict(metric),
        ]


class _DeploySource:
    repo = "example/repository"

    def get_recent_deploys(
        self, *args, **kwargs
    ):
        return [
            {
                "time":
                "2026-07-28T12:03:00+02:00",
                "commit": "abcdef1",
                "environment":
                "payments",
            },
            {
                "time":
                "not-a-time",
                "commit": "badtime",
            },
            {
                "time":
                "2026-07-28T10:02:00Z",
            },
        ]


class SourceProvenanceTests(
    unittest.TestCase
):
    def _state(self):
        return {
            "alert": {
                "service": "payments",
                "labels": {
                    "service":
                    "payments",
                    "environment":
                    "staging",
                    "token":
                    "must-not-survive",
                },
            },
            "incident_window": {
                "start":
                "2026-07-28T09:55:00Z",
                "end":
                "2026-07-28T10:05:00Z",
            },
            "collection_plan": {
                "log_fetch_limit": 20,
            },
        }

    def test_query_spec_is_versioned_stable_and_redacted(
        self,
    ):
        first = query_spec(
            source="loki",
            operation="search",
            service="payments",
            filters={
                "token":
                "must-not-survive",
            },
            window={
                "start": "a",
                "end": "b",
            },
        )
        second = query_spec(
            source="loki",
            operation="search",
            service="payments",
            filters={
                "token":
                "must-not-survive",
            },
            window={
                "start": "a",
                "end": "b",
            },
        )
        serialized = json.dumps(
            first,
            sort_keys=True,
        )
        self.assertEqual(
            first["query_id"],
            second["query_id"],
        )
        self.assertEqual(
            first[
                "query_schema_version"
            ],
            QUERY_SPEC_VERSION,
        )
        self.assertNotIn(
            "must-not-survive",
            serialized,
        )

    def test_log_collection_quarantines_bad_rows_and_tracks_lineage(
        self,
    ):
        with patch.object(
            gather_logs_module,
            "loki",
            _MixedQualityLoki(),
        ):
            collected = gather_logs(
                self._state()
            )
        status = collected[
            "source_status"
        ]["loki"]
        source_provenance = status[
            "provenance"
        ]
        quality = status[
            "data_quality"
        ]
        self.assertEqual(
            source_provenance[
                "provenance_schema_version"
            ],
            CONNECTOR_PROVENANCE_VERSION,
        )
        self.assertEqual(
            source_provenance[
                "source_schema_id"
            ],
            "loki-log-record/v1",
        )
        self.assertEqual(
            source_provenance[
                "backend"
            ],
            "https://loki.example.test",
        )
        self.assertEqual(
            source_provenance[
                "fetched_count"
            ],
            4,
        )
        self.assertEqual(
            source_provenance[
                "reduced_count"
            ],
            1,
        )
        self.assertEqual(
            quality[
                "duplicate_records"
            ],
            1,
        )
        self.assertEqual(
            quality[
                "quarantined_records"
            ],
            2,
        )
        self.assertEqual(
            quality["usable_records"],
            1,
        )
        self.assertNotIn(
            "raw-connector-secret",
            json.dumps(collected, sort_keys=True),
        )
        self.assertEqual(
            collected["logs"][0]["event_time"],
            "2026-07-28T10:00:00Z",
        )
        self.assertEqual(
            collected["logs"][0]["original_timezone"],
            "UTC+02:00",
        )
        query_json = json.dumps(
            source_provenance[
                "query_specification"
            ],
            sort_keys=True,
        )
        self.assertNotIn(
            "must-not-survive",
            query_json,
        )

        normalized = normalize_logs(
            collected
        )
        aggregate_state = {
            **self._state(),
            **collected,
            **normalized,
            "incident_id":
            "INC-PROVENANCE",
        }
        grouped = aggregate_by_labels(
            aggregate_state
        )
        group = grouped[
            "log_groups"
        ][0]
        self.assertEqual(
            group["lineage"][
                "source_query_ids"
            ],
            [
                source_provenance[
                    "query_id"
                ]
            ],
        )
        correlated = correlate({
            **aggregate_state,
            **grouped,
            "metrics": [],
            "deploys": [],
        })
        node = correlated[
            "evidence_graph"
        ]["nodes"][0]
        self.assertIn(
            source_provenance[
                "query_id"
            ],
            node[
                "source_lineage"
            ][
                "source_query_ids"
            ],
        )

        pack = build_evidence_pack({
            **aggregate_state,
            **grouped,
            "source_status":
            collected["source_status"],
            "deterministic_assessment":
            {},
        })
        self.assertIn(
            source_provenance[
                "query_id"
            ],
            pack,
        )
        self.assertIn(
            "quarantined=2",
            pack,
        )
        page = render_review({
            **aggregate_state,
            **grouped,
            "source_status":
            collected["source_status"],
            "interpretation":
            "No supported root cause yet.",
            "interpretation_quality": {
                "abstained": True,
            },
        })
        self.assertIn(
            "Sanitized replay specification",
            page,
        )
        self.assertIn(
            "Fetched → usable",
            page,
        )
        self.assertIn(
            source_provenance[
                "query_id"
            ],
            page,
        )

    def test_provenance_strips_backend_credentials_and_paths(
        self,
    ):
        result = provenance(
            source="loki",
            backend=(
                "https://user:password@"
                "loki.example.test/private"
                "?token=secret"
            ),
            query_specification=
            query_spec(
                source="loki",
                operation="search",
            ),
            source_schema_id=
            "loki-log-record/v1",
        )
        serialized = json.dumps(
            result,
            sort_keys=True,
        )
        self.assertEqual(
            result["backend"],
            "https://loki.example.test",
        )
        self.assertNotIn(
            "password", serialized
        )
        self.assertNotIn(
            "private", serialized
        )

    def test_metric_query_text_is_removed_but_query_id_survives(
        self,
    ):
        with patch.object(
            gather_metrics_module,
            "prometheus",
            _MetricSource(),
        ):
            result = gather_metrics(
                self._state()
            )
        self.assertEqual(
            len(result["metrics"]), 1
        )
        metric = result["metrics"][0]
        self.assertNotIn(
            "query", metric
        )
        self.assertTrue(
            metric[
                "source_query_id"
            ].startswith(
                "qry-prometheus-"
            )
        )
        self.assertEqual(
            metric["timestamp"],
            "2026-07-28T10:04:00Z",
        )
        self.assertEqual(
            metric["original_timestamp"],
            "2026-07-28T12:04:00+02:00",
        )
        self.assertEqual(
            metric["classification"],
            "confidential",
        )
        self.assertEqual(
            metric["event_id"],
            metric["evidence_id"],
        )
        quality = result[
            "source_status"
        ]["prometheus"][
            "data_quality"
        ]
        self.assertEqual(
            quality[
                "duplicate_records"
            ],
            1,
        )

    def test_deployment_connector_quarantines_incomplete_records(
        self,
    ):
        with patch.object(
            gather_deploys_module,
            "github",
            _DeploySource(),
        ):
            result = gather_deploys(
                self._state()
            )
        self.assertEqual(
            len(result["deploys"]), 1
        )
        quality = result[
            "source_status"
        ]["deployments"][
            "data_quality"
        ]
        self.assertEqual(
            quality[
                "quarantined_records"
            ],
            2,
        )
        self.assertTrue(
            result["deploys"][0][
                "source_query_id"
            ].startswith(
                "qry-deployments-"
            )
        )
        self.assertEqual(
            result["deploys"][0]["time"],
            "2026-07-28T10:03:00Z",
        )
        self.assertEqual(
            result["deploys"][0]["original_timestamp"],
            "2026-07-28T12:03:00+02:00",
        )


if __name__ == "__main__":
    unittest.main()
