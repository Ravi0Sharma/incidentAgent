"""Start a local Arize Phoenix server for incident-agent tracing.

Usage:
    .venv/bin/python scripts/start_phoenix.py

Keeps running until Ctrl+C. Uses a project-local working
directory (.phoenix_data/) so nothing is written to $HOME.
UI: http://127.0.0.1:6006
"""

import os
import signal
import sys


_HERE = os.path.dirname(
    os.path.abspath(__file__)
)
_ROOT = os.path.dirname(_HERE)

os.environ.setdefault(
    "PHOENIX_WORKING_DIR",
    os.path.join(
        _ROOT, ".phoenix_data"
    )
)

os.makedirs(
    os.environ[
        "PHOENIX_WORKING_DIR"
    ],
    exist_ok=True
)


def main():

    import phoenix as px

    session = px.launch_app()
    if session is None:
        print()
        print(
            "Phoenix failed to start. "
            "Another Phoenix process may already "
            "be using ports 6006 or 4317."
        )
        print()
        print("Check:")
        print("  lsof -nP -iTCP:6006 -sTCP:LISTEN")
        print("  lsof -nP -iTCP:4317 -sTCP:LISTEN")
        print()
        print("If Phoenix is already running, open:")
        print("  http://localhost:6006/")
        sys.exit(1)

    print()
    print("Phoenix running.")
    print(
        f"  UI:       {session.url}"
    )
    print(
        "  OTLP in:  "
        "http://127.0.0.1:6006"
        "/v1/traces"
    )
    print(
        f"  Data dir: "
        f"{os.environ['PHOENIX_WORKING_DIR']}"
    )
    print()
    print(
        "Enable tracing in the agent:"
    )
    print("  PHOENIX_ENABLED=true")
    print()
    print("Ctrl+C to stop.")

    def _stop(signum, frame):
        print(
            "\nStopping Phoenix..."
        )
        try:
            px.close_app()
        finally:
            sys.exit(0)

    signal.signal(
        signal.SIGINT, _stop
    )
    signal.signal(
        signal.SIGTERM, _stop
    )
    signal.signal(
        signal.SIGHUP,
        signal.SIG_IGN
    )

    signal.pause()


if __name__ == "__main__":
    main()
