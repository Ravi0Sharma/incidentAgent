import os

import yaml


_CONFIG_PATH = os.getenv(
    "SERVICES_CONFIG_PATH",
    os.path.join(
        os.path.dirname(
            os.path.dirname(
                os.path.abspath(__file__)
            )
        ),
        "config",
        "services.yaml"
    )
)


_DEFAULTS = {
    "tier": 2,
    "customer_facing": False,
    "owner": "unknown",
    "runbook": None,
    "description": ""
}


def _load():

    if not os.path.exists(
        _CONFIG_PATH
    ):
        return {
            "services": {},
            "defaults": _DEFAULTS
        }

    with open(_CONFIG_PATH) as f:

        data = yaml.safe_load(f) or {}

    return {
        "services": data.get(
            "services", {}
        ) or {},
        "defaults": {
            **_DEFAULTS,
            **(
                data.get(
                    "defaults", {}
                ) or {}
            )
        }
    }


_REGISTRY = _load()


def get_service(name):

    if not name:
        return dict(
            _REGISTRY["defaults"]
        )

    svc = _REGISTRY["services"].get(
        name
    )

    if not svc:
        return dict(
            _REGISTRY["defaults"]
        )

    merged = {
        **_REGISTRY["defaults"],
        **svc
    }

    return merged


def list_services():

    return sorted(
        _REGISTRY["services"].keys()
    )


def dependencies_for(name):

    svc = get_service(name)
    deps = svc.get(
        "dependencies", []
    ) or []

    return [
        str(d)
        for d in deps
        if d
    ]


def related_services(name):

    related = []

    for dep in dependencies_for(name):
        if dep not in related:
            related.append(dep)

    for svc_name, svc in (
        _REGISTRY["services"].items()
    ):
        deps = (
            svc.get(
                "dependencies", []
            )
            or []
        )
        if (
            name in deps
            and svc_name not in related
        ):
            related.append(svc_name)

    return related


def reload():

    global _REGISTRY
    _REGISTRY = _load()
    return _REGISTRY
