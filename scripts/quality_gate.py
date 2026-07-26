"""Run the deterministic local/CI quality gate without a live LLM."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)

MYPY_TARGETS = [
    "utils/redaction.py",
    "utils/log_store.py",
    "utils/render_safety.py",
    "utils/tool_budget.py",
    "utils/model_usage.py",
    "utils/review_gate.py",
    "webhook/alert_contract.py",
    "webhook/rate_limit.py",
    "webhook/state_sync.py",
]

# The product-critical path from deterministic correlation through grounded
# interpretation and review. Deferred publishers, postmortem work and runtime
# connectors remain visible in the whole-repository ratchet below, but do not
# dilute this stricter signal.
CORE_COVERAGE_TARGETS = [
    "graph/nodes/classify_severity.py",
    "graph/nodes/correlate.py",
    "graph/nodes/scope_expansion.py",
    "graph/nodes/semantic_correlate.py",
    "graph/nodes/interpret_incident.py",
    "graph/nodes/integrate_targeted_evidence.py",
    "utils/candidate_scoring.py",
    "utils/correlation_tools.py",
    "utils/data_quality.py",
    "utils/evidence.py",
    "utils/evidence_pack.py",
    "utils/incident_features.py",
    "utils/incident_window.py",
    "utils/interpretation_contract.py",
    "utils/interpretation_quality.py",
    "utils/investigation_loop.py",
    "utils/log_normalizer.py",
    "utils/log_store.py",
    "utils/redaction.py",
    "utils/review_gate.py",
    "utils/signal_observations.py",
    "utils/tool_budget.py",
    "webhook/alert_contract.py",
    "webhook/interpretation.py",
    "webhook/timeline.py",
]

SECURITY_COVERAGE_TARGETS = [
    "utils/log_store.py",
    "utils/redaction.py",
    "utils/render_safety.py",
    "utils/review_gate.py",
    "utils/tool_budget.py",
    "webhook/alert_contract.py",
    "webhook/rate_limit.py",
]


def _run(label: str, command: list[str], env: dict[str, str]):
    print(f"\n== {label} ==", flush=True)
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def main():
    env = os.environ.copy()
    env.update({
        "SKIP_LLM": "true",
        "OPENAI_API_KEY": "test-provider-key",
        "PUBLISH_EXTERNAL": "false",
        "PHOENIX_ENABLED": "false",
    })
    bin_dir = PYTHON.parent
    steps = [
        ("repository secret scan", [str(PYTHON), "scripts/check_repository_secrets.py"]),
        ("ruff", [str(bin_dir / "ruff"), "check", "."]),
        ("mypy", [str(bin_dir / "mypy"), *MYPY_TARGETS]),
        ("compile", [str(PYTHON), "-m", "compileall", "-q", ".", "-x", "(^|/)(.venv|data|output)/"]),
        ("prompt budgets", [str(PYTHON), "scripts/check_prompt_budget.py"]),
        ("coverage reset", [str(bin_dir / "coverage"), "erase"]),
        ("tests with branch coverage", [str(bin_dir / "coverage"), "run", "-m", "unittest", "discover", "-s", "tests"]),
        # Keep broad visibility without forcing deferred adapters to masquerade
        # as core product coverage. Stricter, explicit scopes follow below.
        ("whole-repository coverage ratchet", [
            str(bin_dir / "coverage"), "report", "--fail-under=74",
        ]),
        ("core branch coverage", [
            str(bin_dir / "coverage"),
            "report",
            "--fail-under=80",
            *CORE_COVERAGE_TARGETS,
        ]),
        ("security branch coverage", [
            str(bin_dir / "coverage"),
            "report",
            "--fail-under=90",
            *SECURITY_COVERAGE_TARGETS,
        ]),
    ]
    for label, command in steps:
        _run(label, command, env)
    print("\nquality gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
