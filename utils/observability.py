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

from settings import ENVIRONMENT


_INITIALIZED = False


def init_tracing():

    global _INITIALIZED

    if _INITIALIZED:
        return

    # Phoenix instrumentation can capture complete graph state and model
    # inputs/outputs. It is therefore a local synthetic-data tool only.
    if ENVIRONMENT != "local":
        return

    if os.getenv(
        "PHOENIX_ENABLED",
        "false"
    ).lower() != "true":
        return

    if os.getenv(
        "PHOENIX_COMPACT_TRACES",
        "true"
    ).lower() == "true":
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

    endpoint = os.getenv(
        "PHOENIX_COLLECTOR_ENDPOINT",
        "http://127.0.0.1:6006/v1/traces"
    )

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
        "[observability] Phoenix "
        f"tracing enabled -> "
        f"{endpoint} "
        f"(project={project})"
    )

    _INITIALIZED = True
