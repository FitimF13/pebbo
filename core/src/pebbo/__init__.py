"""Pebbo core service."""

import os

__version__ = "0.1.0"

# Telemetry of third-party libraries is switched off before any of them is imported.
for _key in ("ORT_DISABLE_TELEMETRY", "HF_HUB_DISABLE_TELEMETRY", "DO_NOT_TRACK", "DISABLE_TELEMETRY"):
    os.environ[_key] = "1"
