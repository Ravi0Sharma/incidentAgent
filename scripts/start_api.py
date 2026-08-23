#!/usr/bin/env python3
"""Shell-free API entry point used by the locked runtime image."""

import os
import sys
from pathlib import Path

import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import settings
from utils.runtime_config import validate_runtime_config


def main():
    """Validate the selected runtime before exposing an API listener."""
    validate_runtime_config(settings)
    uvicorn.run(
        "webhook.api:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )


if __name__ == "__main__":
    main()
