from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from clients.cloudwatch_client import (
    CloudWatchLogsClient,
    CloudWatchMetricsClient,
)
from graph.nodes import gather_logs as gather_logs_module
from graph.nodes import gather_metrics as gather_metrics_module
from utils.resilience import ConnectorRequestError, SourceUnavailable
from webhook.alert_contract import validate_alert_payload, AlertContractError
from webhook.cloudwatch import cloudwatch_alarm_to_alert


SOURCE_MAP = {
    "version": "cloudwatch-source-map/v1",
    "alarms": {
        "checkout-errors": {
            "service": "checkout",
            "environment": "production",
            "severity": "critical",
        },
    },
    "services": {
        "checkout": {
            "log_groups": ["/aws/app/checkout"],
            "metrics": {
                "error_rate": {
                    "namespace": "Example/Application",
                    "metric_name": "ErrorRate",
                    "statistic": "Average",
                    "period_seconds": 60,
                    "dimensions": {"ServiceName": "checkout"},
                },
            },
        },
    },
}


WINDOW = {
    "start": "2026-08-09T10:00:00Z",
    "end": "2026-08-09T10:10:00Z",
}


class _LogsApi:
    def __init__(self, final_status="Complete"):
        self.final_status = final_status
        self.started = []
        self.polls = 0

    def start_query(self, **kwargs):
        self.started.append(kwargs)
        return {
            "queryId": "native-query-secret",
            "ResponseMetadata": {"RequestId": "start-request"},
        }

    def get_query_results(self, **kwargs):
        self.polls += 1
        if self.polls == 1 and self.final_status == "Complete":
            return {"status": "Running", "results": []}
        return {
            "status": self.final_status,
            "results": [
                [
                    {"field": "@timestamp", "value": "2026-08-09 10:01:00.000"},
                    {"field": "@message", "value": "connection refused"},
                    {"field": "@logStream", "value": "instance-1"},
                    {"field": "@log", "value": "/aws/app/checkout"},
                ],
                [
                    {"field": "@timestamp", "value": "2026-08-09 10:02:00.000"},
                    {"field": "@message", "value": "retry failed"},
                ],
            ],
            "statistics": {"recordsMatched": 7},
            "ResponseMetadata": {"RequestId": "result-request"},
        }


class _MetricsApi:
    def __init__(self, keep_token=False, status="Complete"):
        self.calls = []
        self.keep_token = keep_token
        self.status = status

    def get_metric_data(self, **kwargs):
        self.calls.append(kwargs)
        page = len(self.calls)
        response = {
            "MetricDataResults": [{
                "Id": "m0",
                "StatusCode": self.status,
                "Timestamps": [
                    datetime(2026, 8, 9, 10, page, tzinfo=timezone.utc),
                ],
                "Values": [float(page)],
            }],
            "ResponseMetadata": {"RequestId": f"metric-{page}"},
        }
        if self.keep_token or page == 1:
            response["NextToken"] = f"page-{page + 1}"
        return response


class CloudWatchConnectorTests(unittest.TestCase):
    def _state(self):
        return {
            "alert": {
                "service": "checkout",
                "labels": {
                    "service": "checkout",
                    "log_group": "/attacker/chosen",
                    "namespace": "Attacker/Metric",
                },
            },
            "incident_window": WINDOW,
            "collection_plan": {"log_fetch_limit": 2},
        }

    def test_logs_use_only_allowlisted_groups_and_fixed_query(self):
        api = _LogsApi()
        client = CloudWatchLogsClient(
            api,
            SOURCE_MAP,
            "eu-north-1",
            query_limit=2,
            poll_attempts=3,
            poll_interval=0,
        )
        rows = client.query_logs(
            "checkout",
            {"log_group": "/attacker/chosen"},
            WINDOW,
            limit=2,
        )
        request = api.started[0]
        self.assertEqual(request["logGroupNames"], ["/aws/app/checkout"])
        self.assertNotIn("attacker", request["queryString"].lower())
        self.assertNotIn("native-query-secret", str(rows))
        self.assertEqual(len(rows), 2)
        self.assertTrue(client.last_query_metadata["truncated"])
        self.assertEqual(client.last_query_metadata["matched_count"], 7)

    def test_unknown_service_fails_before_an_aws_call(self):
        api = _LogsApi()
        client = CloudWatchLogsClient(api, SOURCE_MAP, "eu-north-1")
        with self.assertRaises(ConnectorRequestError) as caught:
            client.query_logs("attacker-service", {}, WINDOW)
        self.assertEqual(caught.exception.category, "invalid_query")
        self.assertEqual(api.started, [])

    def test_terminal_query_status_is_an_explicit_failure(self):
        client = CloudWatchLogsClient(
            _LogsApi(final_status="Timeout"),
            SOURCE_MAP,
            "eu-north-1",
            poll_attempts=1,
            poll_interval=0,
        )
        with self.assertRaises(SourceUnavailable) as caught:
            client.query_logs("checkout", {}, WINDOW)
        self.assertIn("Timeout", caught.exception.diagnostic)

    def test_metrics_are_allowlisted_and_pagination_is_bounded(self):
        api = _MetricsApi(keep_token=True, status="PartialData")
        client = CloudWatchMetricsClient(
            api,
            SOURCE_MAP,
            "eu-north-1",
            page_limit=1,
        )
        metrics = client.query_metrics(
            "checkout",
            {"namespace": "Attacker/Metric"},
            WINDOW,
        )
        self.assertEqual(len(api.calls), 1)
        query = api.calls[0]["MetricDataQueries"][0]
        native = query["MetricStat"]["Metric"]
        self.assertEqual(native["Namespace"], "Example/Application")
        self.assertEqual(
            native["Dimensions"],
            [{"Name": "ServiceName", "Value": "checkout"}],
        )
        self.assertTrue(metrics[0]["partial"])
        self.assertTrue(client.last_query_metadata["truncated"])

    def test_collectors_emit_cloudwatch_provenance_and_partial_status(self):
        logs_client = CloudWatchLogsClient(
            _LogsApi(), SOURCE_MAP, "eu-north-1",
            query_limit=2, poll_attempts=3, poll_interval=0,
        )
        metrics_client = CloudWatchMetricsClient(
            _MetricsApi(keep_token=True, status="PartialData"),
            SOURCE_MAP,
            "eu-north-1",
            page_limit=1,
        )
        with (
            patch.object(gather_logs_module, "LOG_SOURCE", "cloudwatch"),
            patch.object(gather_logs_module, "cloudwatch_logs", logs_client),
        ):
            logs = gather_logs_module.gather_logs(self._state())
        with (
            patch.object(gather_metrics_module, "METRIC_SOURCE", "cloudwatch"),
            patch.object(gather_metrics_module, "cloudwatch_metrics", metrics_client),
        ):
            metrics = gather_metrics_module.gather_metrics(self._state())
        log_status = logs["source_status"]["cloudwatch_logs"]
        metric_status = metrics["source_status"]["cloudwatch_metrics"]
        self.assertEqual(log_status["status"], "partial")
        self.assertEqual(log_status["provenance"]["source_request_id"], "result-request")
        self.assertEqual(metric_status["status"], "partial")
        self.assertEqual(
            metrics["metrics"][0]["connector_metadata"]["source"],
            "cloudwatch_metrics",
        )

    def test_alarm_mapping_owns_service_environment_and_severity(self):
        event = {
            "id": "event-1",
            "source": "aws.cloudwatch",
            "detail-type": "CloudWatch Alarm State Change",
            "region": "eu-north-1",
            "time": "2026-08-09T10:00:00Z",
            "detail": {
                "alarmName": "checkout-errors",
                "state": {
                    "value": "ALARM",
                    "reason": "threshold crossed",
                    "timestamp": "2026-08-09T10:00:00Z",
                },
            },
        }
        alert = cloudwatch_alarm_to_alert(event, SOURCE_MAP)
        self.assertEqual(alert["service"], "checkout")
        self.assertEqual(alert["status"], "firing")
        validated = validate_alert_payload(
            alert,
            max_alerts=1,
            max_labels=20,
            max_annotations=20,
            max_field_length=4096,
            supported_services={"checkout"},
            supported_environments={"production"},
            default_environment="production",
        )
        self.assertEqual(validated, [alert])

    def test_unknown_alarm_and_insufficient_data_fail_closed(self):
        base = {
            "source": "aws.cloudwatch",
            "detail-type": "CloudWatch Alarm State Change",
            "time": "2026-08-09T10:00:00Z",
            "detail": {
                "alarmName": "unknown-alarm",
                "state": {"value": "ALARM"},
            },
        }
        with self.assertRaises(AlertContractError) as unknown:
            cloudwatch_alarm_to_alert(base, SOURCE_MAP)
        self.assertEqual(unknown.exception.code, "unsupported_cloudwatch_alarm")
        base["detail"]["alarmName"] = "checkout-errors"
        base["detail"]["state"]["value"] = "INSUFFICIENT_DATA"
        with self.assertRaises(AlertContractError) as state:
            cloudwatch_alarm_to_alert(base, SOURCE_MAP)
        self.assertEqual(state.exception.code, "unsupported_cloudwatch_state")


if __name__ == "__main__":
    unittest.main()
