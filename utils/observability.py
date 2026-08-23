"""OpenTelemetry tracing to a local Arize Phoenix server.

Enable with:

    PHOENIX_ENABLED=true

The Phoenix UI must be running separately (see README.md
under "Observability").  When disabled, this module is a no-op.

Two instrumentors are activated when enabled:

  - openinference.instrumentation.langchain
    Auto-traces every LangGraph node (interpret_incident,
    deep_rca, draft_postmortem, ...) as a span with its
    input/output state.

  - openinference.instrumentation.openai
    Auto-traces every openai.ChatCompletion call the LLM
    nodes make, including full prompt, response, and
    tool-call sub-spans.
"""

import os

from settings import ENVIRONMENT, OTEL_EXPORTER_OTLP_ENDPOINT, SERVICE_VERSION
from utils.egress import assert_egress_url


_INITIALIZED = False


def init_tracing():

    global _INITIALIZED

    if _INITIALIZED:
        return

    local_phoenix = (
        ENVIRONMENT == "local"
        and os.getenv("PHOENIX_ENABLED", "false").lower() == "true"
    )
    endpoint = OTEL_EXPORTER_OTLP_ENDPOINT
    if not endpoint and local_phoenix:
        endpoint = os.getenv(
            "PHOENIX_COLLECTOR_ENDPOINT",
            "http://127.0.0.1:6006/v1/traces",
        )
    if not endpoint:
        return
    assert_egress_url(endpoint, source="otel")

    if (
        ENVIRONMENT != "local"
        or os.getenv("PHOENIX_COMPACT_TRACES", "true").lower() == "true"
    ):
        # Keep prompts and model output out of Phoenix by default. Set this to
        # false only while debugging with approved synthetic local data.
        os.environ.setdefault(
            "OPENINFERENCE_HIDE_INPUTS",
            "true"
        )
        os.environ.setdefault(
            "OPENINFERENCE_HIDE_OUTPUTS",
            "true"
        )

    try:
        from phoenix.otel import (
            register
        )
        from openinference.instrumentation.langchain import (
            LangChainInstrumentor
        )
        from openinference.instrumentation.openai import (
            OpenAIInstrumentor
        )
    except ImportError as e:
        print(
            "[observability] "
            "phoenix packages not "
            "installed, skipping "
            f"({e})"
        )
        return

    project = os.getenv(
        "PHOENIX_PROJECT_NAME",
        "incident-agent"
    )

    register(
        project_name=project,
        endpoint=endpoint,
        auto_instrument=False,
        set_global_tracer_provider=True
    )
    os.environ.setdefault("OTEL_SERVICE_NAME", "incident-agent")
    os.environ.setdefault("OTEL_RESOURCE_ATTRIBUTES", f"service.version={SERVICE_VERSION}")

    LangChainInstrumentor().instrument()
    OpenAIInstrumentor().instrument()

    try:
        from openinference.instrumentation.langchain._tracer import (
            OpenInferenceTracer
        )
        if not hasattr(
            OpenInferenceTracer,
            "on_interrupt"
        ):
            OpenInferenceTracer.on_interrupt = (
                lambda self, *a, **kw: None
            )
        if not hasattr(
            OpenInferenceTracer,
            "on_resume"
        ):
            OpenInferenceTracer.on_resume = (
                lambda self, *a, **kw: None
            )
    except Exception:
        pass

    print(
        "[observability] OTLP tracing enabled -> "
        f"{endpoint} "
        f"(project={project})"
    )

    _INITIALIZED = True
