"""Who may reach the core over the network.

The control centre and the PC app have no sign-in, so they answer only on this computer.
Pebbo bodies and paired phones authenticate with their own token and may connect from the
home network, never from a public address. A paired second instance (the office Pebbo) may
deliver handoffs from the home network or a private VPN. This lets the core listen on the
local network (``PEBBO_HOST=0.0.0.0``) without opening the control centre to it.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

from pebbo.netguard import is_local_address

# Paths a body on the home network may use.
BODY_PATHS = ("/xiaozhi/",)
# Paths another paired Pebbo instance may use, also over a private VPN such as Headscale.
PEER_PATHS = ("/api/peer/",)
# Paths a paired phone on the home network may use. Every route except pairing needs the
# phone's token (see pebbo.phones).
APP_PATHS = ("/api/app/",)
# Paths of devices with their own token. They are not browsers, so requests with an Origin
# header are refused there.
TOKEN_PATHS = BODY_PATHS + PEER_PATHS + APP_PATHS


def _address(scope: Scope) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    client = scope.get("client")
    if not client:
        return None
    try:
        address = ipaddress.ip_address(client[0])
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


# Host names under which the control centre and the PC app are opened on this computer.
LOCAL_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return bytes(value).decode("latin-1")
    return None


def _hostname(value: str) -> str:
    """The host name of a Host header or an origin, without scheme, port or brackets."""
    value = value.split("://", 1)[-1].split("/", 1)[0].lower()
    if value.startswith("["):
        return value[1:].split("]", 1)[0]
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def _from_this_computer(scope: Scope) -> bool:
    """Whether a loopback request really comes from a page of Pebbo on this computer.

    A web page on any other site, open in the owner's browser, can also send requests to
    127.0.0.1. Browsers mark them with their Origin, and DNS rebinding shows up as a foreign
    Host header, so both must name this computer.
    """
    host = _header(scope, b"host")
    if host is not None and _hostname(host) not in LOCAL_NAMES:
        return False
    origin = _header(scope, b"origin")
    return origin is None or _hostname(origin) in LOCAL_NAMES


def _clean(path: str) -> bool:
    """Whether a path has no tricks like ``/api/app/../control/``."""
    return "\\" not in path and not any(part in (".", "..") for part in path.split("/"))


def allowed(scope: Scope) -> bool:
    """Whether a request may reach this path from where it comes from."""
    address = _address(scope)
    if address is None:
        # In-process clients, such as the test client, have no network address.
        client = scope.get("client")
        return client is None or client[0] == "testclient"
    path = str(scope.get("path", ""))
    if path.startswith(TOKEN_PATHS) and (_header(scope, b"origin") is not None or not _clean(path)):
        # Bodies, phones and other instances are not browsers; a browser page must not speak for them.
        return False
    if address.is_loopback:
        return path.startswith(TOKEN_PATHS) or _from_this_computer(scope)
    if path.startswith(PEER_PATHS):
        return is_local_address(str(address)) and not address.is_link_local and not address.is_multicast
    return path.startswith(BODY_PATHS + APP_PATHS) and address.is_private and not address.is_link_local


class LocalAccess:
    """ASGI middleware that refuses requests and WebSockets from where they are not allowed."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and not allowed(scope):
            await self._refuse(scope, send)
            return
        await self._app(scope, receive, send)

    @staticmethod
    async def _refuse(scope: Scope, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4403})
            return
        body = b"Not available from this address."
        headers: list[Any] = [(b"content-type", b"text/plain"), (b"content-length", str(len(body)).encode())]
        await send({"type": "http.response.start", "status": 403, "headers": headers})
        await send({"type": "http.response.body", "body": body})
