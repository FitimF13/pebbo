"""Prepare the local Ollama model Pebbo talks to."""

from __future__ import annotations

import ipaddress
import json
import urllib.request
from typing import Any
from urllib.parse import urlsplit

from pebbo.netguard import is_local_address

CONTEXT_LENGTH = 4096


def _api(base_url: str, path: str, body: dict[str, Any], timeout: float) -> bytes:
    parts = urlsplit(base_url)
    if parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Pebbo only prepares models on a local Ollama server.")
    request = urllib.request.Request(  # noqa: S310 - the scheme and host are checked above
        f"{parts.scheme}://{parts.netloc}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return bytes(response.read())


def llm_request(base_url: str, path: str, body: dict[str, Any], timeout: float) -> bytes:
    """A request to the Ollama server of a compute device, on this computer or the home network.

    Unlike model preparation, conversations, decisions and summaries also run on other
    computers the owner listed (see ``pebbo.models_router``). Public addresses are refused
    here, and the runtime network guard blocks them as well.
    """
    parts = urlsplit(base_url)
    host = parts.hostname or ""
    if parts.scheme not in ("http", "https") or not host:
        raise ValueError("The language model address is not valid.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass  # A host name; the network guard checks where it resolves to.
    else:
        if not is_local_address(host):
            raise ValueError("Pebbo only talks to language models on the home network.")
    request = urllib.request.Request(  # noqa: S310 - the scheme and host are checked above
        f"{parts.scheme}://{parts.netloc}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return bytes(response.read())


def create_model(base_url: str, model: str, base_model: str) -> None:
    """Derive Pebbo's model from an installed base model with a small context window.

    A small context keeps the model and Whisper together in 8 GB of GPU memory.
    """
    _api(
        base_url,
        "/api/create",
        {"model": model, "from": base_model, "parameters": {"num_ctx": CONTEXT_LENGTH}, "stream": False},
        timeout=600,
    )


def warm_up(base_url: str, model: str) -> None:
    """Load the model into memory and keep it there, so the first answer is fast."""
    _api(base_url, "/api/generate", {"model": model, "keep_alive": -1, "stream": False}, timeout=300)
