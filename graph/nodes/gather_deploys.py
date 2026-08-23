from clients.github_client import (
    github
)
from settings import CONNECTORS_ENABLED
from utils.connector_result import (
    provenance,
    query_spec,
    source_result,
    status_for_count,
)
from utils.data_quality import (
    assess_records,
    empty_quality,
)
from utils.evidence import canonical_evidence
from utils.resilience import ConnectorRequestError


def gather_deploys(state):

    alert = state["alert"]

    service = (
        alert.get("service")
        or alert
        .get("labels", {})
        .get("service", "")
    )
    source_schema_id = (
        "github-deployment/v1"
    )
    query_description = query_spec(
        source="deployments",
        operation=
        "github_deployments_list",
        service=service,
        window=state.get(
            "incident_window", {}
        ),
        limits={
            "page_size": 30,
            "lookback_policy":
            "DEPLOY_LOOKBACK_HOURS",
        },
        query_template=(
            "GET /repos/{configured_repo}/"
            "deployments?environment="
            "{service}"
        ),
    )

    try:
        if not CONNECTORS_ENABLED:
            raise RuntimeError("connector kill switch is active")
        raw_deploys = github.get_recent_deploys(
            service,
            window=state.get("incident_window")
        )
        deploys, quality = assess_records(
            raw_deploys,
            source_schema_id=
            source_schema_id,
            timestamp_fields=(
                "time",
            ),
            required_fields=(
                "time",
                "commit",
            ),
            window=state.get(
                "incident_window", {}
            ),
            quarantine_invalid_timestamp=
            True,
        )
        quality["service_attribution"] = {
            "method": "configured_deploy_environment_scope",
            "service": service,
            "unattributed_records": 0,
        }
        provenance_data = provenance(
            source="deployments",
            backend=getattr(github, "repo", "mock-github"),
            query_specification=
            query_description,
            source_schema_id=
            source_schema_id,
            connector_version=
            "github-deployments-connector/v2",
            window=state.get("incident_window", {}),
            result_count=len(
                raw_deploys
            ),
            fetched_count=len(
                raw_deploys
            ),
            reduced_count=len(
                deploys
            ),
        )
        for deploy in deploys:
            deploy[
                "source_query_id"
            ] = provenance_data[
                "query_id"
            ]
            deploy["connector_metadata"] = provenance_data
            evidence_payload = {
                key: value
                for key, value in deploy.items()
                if key not in {
                    "connector_metadata",
                    "event_time",
                    "received_at",
                    "original_timestamp",
                    "original_timezone",
                    "clock_quality",
                    "timestamp_source_field",
                    "source_query_id",
                }
            }
            canonical = canonical_evidence(
                evidence_type="deploy",
                source="deployments",
                payload=evidence_payload,
                timestamp=deploy.get("original_timestamp"),
                received_at=deploy.get("received_at"),
                service=service,
                environment=deploy.get("environment"),
                lineage=provenance_data,
                collection_revision=provenance_data.get(
                    "collection_revision", 1
                ),
            )
            deploy["time"] = canonical["event_time"]
            deploy["event_id"] = canonical["evidence_id"]
            deploy["canonical_evidence_schema_version"] = canonical.pop(
                "evidence_schema_version"
            )
            deploy.update(canonical)
        return {
            "deploys": deploys,
            "source_status": {
                "deployments": {
                    **source_result(
                        status_for_count(len(deploys)),
                        provenance_data,
                    ),
                    "records_fetched":
                    len(raw_deploys),
                    "records_usable":
                    len(deploys),
                    "deploys_returned": len(deploys),
                    "window": state.get("incident_window", {}),
                    "data_quality":
                    quality,
                }
            }
        }
    except Exception as exc:
        category = exc.category if isinstance(exc, ConnectorRequestError) else "failed"
        return {
            "deploys": [],
            "source_status": {
                "deployments": {
                    **source_result(
                        category,
                        provenance(
                            source="deployments",
                            backend=getattr(github, "repo", "mock-github"),
                            query_specification=
                            query_description,
                            source_schema_id=
                            source_schema_id,
                            connector_version=
                            "github-deployments-connector/v2",
                            window=state.get("incident_window", {}),
                        ),
                        diagnostic=(
                            exc.diagnostic if isinstance(exc, ConnectorRequestError)
                            else type(exc).__name__
                        ),
                    ),
                    "window": state.get("incident_window", {}),
                    "data_quality":
                    empty_quality(
                        source_schema_id,
                        source_error_records=1,
                    ),
                }
            }
        }
