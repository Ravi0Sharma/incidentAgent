from datetime import (
    datetime,
    timedelta
)

from utils.service_registry import (
    get_service
)


def _parse(ts):

    if not ts:
        return None

    try:
        return datetime.fromisoformat(
            ts.replace("Z", "+00:00")
        )
    except (
        ValueError,
        AttributeError
    ):
        return None


DEPLOY_WINDOW = timedelta(minutes=15)


def _related_deploys(
    group_first_seen,
    deploys,
    service=None,
):

    first = _parse(
        group_first_seen
    )

    if first is None:
        return []

    out = []

    for d in deploys or []:

        deploy_service = d.get("environment")
        if (
            service
            and deploy_service
            and deploy_service != service
        ):
            continue

        d_time = _parse(
            d.get("time")
        )

        if d_time is None:
            continue

        delta = first - d_time

        if (
            timedelta(0)
            <= delta
            <= DEPLOY_WINDOW
        ):
            out.append({
                "time":
                d.get("time"),
                "commit":
                d.get("commit"),
                "environment":
                d.get(
                    "environment"
                ),
                "minutes_before_first_error":
                round(
                    delta
                    .total_seconds()
                    / 60,
                    1
                )
            })

    return out


def enrich_groups(state):

    groups = state.get(
        "log_groups", []
    )
    deploys = state.get(
        "deploys", []
    )

    enriched = []

    for g in groups:

        svc_name = (
            g.get("labels", {})
            .get("service")
        )

        svc = get_service(svc_name)

        enriched.append({
            **g,
            "owner": svc.get(
                "owner", "unknown"
            ),
            "runbook": svc.get(
                "runbook"
            ),
            "tier": svc.get("tier"),
            "related_deploys":
            _related_deploys(
                g.get("first_seen"),
                deploys,
                service=svc_name,
            )
        })

    return {
        "log_groups": enriched
    }
