"""Start the incident-agent web UI with Phoenix tracing.

Usage:
    .venv/bin/python scripts/start_incident_agent.py

This starts Phoenix when needed, then starts the FastAPI webhook UI
with PHOENIX_ENABLED=true so traces are sent to Phoenix.
"""

import argparse
import os
import socket
import subprocess
import time
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "bin" / "python"
UVICORN = ROOT / ".venv" / "bin" / "uvicorn"


def port_open(host, port):
    with socket.socket(
        socket.AF_INET, socket.SOCK_STREAM
    ) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def wait_for_port(host, port, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(host, port):
            return True
        time.sleep(0.25)
    return False


def start_process(name, cmd, env):
    print(f"[start] {name}: {' '.join(map(str, cmd))}")
    return subprocess.Popen(
        [str(part) for part in cmd],
        cwd=ROOT,
        env=env
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Start Phoenix and the incident-agent UI together."
        )
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Incident-agent web port."
    )
    parser.add_argument(
        "--phoenix-port",
        type=int,
        default=6006,
        help="Phoenix UI and HTTP collector port."
    )
    parser.add_argument(
        "--phoenix-grpc-port",
        type=int,
        default=4317,
        help="Phoenix gRPC/OTLP port."
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open browser tabs."
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Run with deterministic LLM stubs."
    )
    args = parser.parse_args()

    if not PYTHON.exists():
        print(
            "[start] missing .venv. Create it and install "
            "requirements first."
        )
        return 1

    env = os.environ.copy()
    env.setdefault(
        "PHOENIX_WORKING_DIR",
        str(ROOT / ".phoenix_data")
    )
    env["PHOENIX_ENABLED"] = "true"
    # Keep graph state, prompts and model output out of traces by default.
    # An operator may explicitly set this to false only for approved,
    # synthetic local debugging.
    env.setdefault("PHOENIX_COMPACT_TRACES", "true")
    env.setdefault(
        "PHOENIX_COLLECTOR_ENDPOINT",
        (
            f"http://{args.host}:"
            f"{args.phoenix_port}/v1/traces"
        )
    )
    env.setdefault(
        "PHOENIX_PROJECT_NAME",
        "incident-agent"
    )
    if args.no_llm:
        env["SKIP_LLM"] = "true"

    children = []
    phoenix_url = (
        f"http://{args.host}:{args.phoenix_port}"
    )
    agent_url = f"http://{args.host}:{args.port}"

    try:
        if port_open(args.host, args.phoenix_port):
            print(
                "[start] Phoenix already running -> "
                f"{phoenix_url}"
            )
        else:
            if port_open(
                args.host,
                args.phoenix_grpc_port
            ):
                print(
                    "[start] Phoenix UI is not reachable, "
                    "but gRPC port "
                    f"{args.phoenix_grpc_port} is busy."
                )
                print(
                    "[start] Stop the process using it, or "
                    "open the already-running Phoenix if "
                    "it exists."
                )
                print(
                    "        lsof -nP -iTCP:"
                    f"{args.phoenix_grpc_port} "
                    "-sTCP:LISTEN"
                )
                return 1

            children.append(
                start_process(
                    "phoenix",
                    [
                        PYTHON,
                        "scripts/start_phoenix.py"
                    ],
                    env
                )
            )
            if not wait_for_port(
                args.host,
                args.phoenix_port,
                timeout=45
            ):
                print(
                    "[start] Phoenix did not become ready "
                    f"on {phoenix_url}."
                )
                return 1
            print(
                "[start] Phoenix ready -> "
                f"{phoenix_url}"
            )

        if port_open(args.host, args.port):
            print(
                "[start] incident-agent port is busy: "
                f"{agent_url}"
            )
            print(
                "        Stop that server or choose "
                "another --port."
            )
            return 1

        children.append(
            start_process(
                "incident-agent",
                [
                    UVICORN,
                    "webhook.api:app",
                    "--host",
                    args.host,
                    "--port",
                    str(args.port)
                ],
                env
            )
        )

        if not wait_for_port(
            args.host,
            args.port,
            timeout=30
        ):
            print(
                "[start] incident-agent did not become "
                f"ready on {agent_url}."
            )
            return 1

        print()
        print("[start] ready")
        print(f"  incident-agent: {agent_url}")
        print(f"  phoenix:        {phoenix_url}")
        print()
        print("Press Ctrl+C to stop.")

        if not args.no_browser:
            webbrowser.open(agent_url)
            webbrowser.open(phoenix_url)

        while True:
            for child in children:
                code = child.poll()
                if code is not None:
                    print(
                        "[start] child process exited "
                        f"with code {code}"
                    )
                    return code
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[start] stopping...")
        return 0
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in reversed(children):
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()


if __name__ == "__main__":
    raise SystemExit(main())
