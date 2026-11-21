"""Runtime outbound connection guard.

Pebbo is local first: the process may only talk to loopback, private network addresses
and hosts the owner explicitly enabled. This guard enforces that at the socket level, so a
dependency with a forgotten telemetry call or a public default server cannot leak data.
"""

from __future__ import annotations

import ipaddress
import socket
import sys
import threading
from collections.abc import Callable, Iterable
from typing import Any

from loguru import logger

_lock = threading.Lock()
_allowed_hosts: set[str] = set()
_allowed_ips: set[str] = set()
_installed = False
_original_connect: Callable[..., Any] = socket.socket.connect
_original_connect_ex: Callable[..., Any] = socket.socket.connect_ex
_original_sendto: Callable[..., Any] = socket.socket.sendto
_original_getaddrinfo: Callable[..., Any] = socket.getaddrinfo

# On Windows, asyncio's default event loop connects and sends datagrams through the IOCP
# proactor (ConnectEx, WSASendTo), which bypasses the socket methods above. Guard it too.
if sys.platform == "win32":
    from asyncio.windows_events import IocpProactor

    _original_proactor_connect: Callable[..., Any] = IocpProactor.connect
    _original_proactor_sendto: Callable[..., Any] = IocpProactor.sendto


class OutboundConnectionBlocked(ConnectionRefusedError):
    """Raised when code tries to reach a host that is not allowed."""


def is_local_address(address: str) -> bool:
    """Return whether an IP address is not on the public internet.

    This covers loopback, private and link-local ranges, multicast, and the shared address
    space that private networks such as Headscale or Tailscale use (100.64.0.0/10).
    """
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not ip.is_global or ip.is_multicast


def _target_host(address: Any) -> str | None:
    if isinstance(address, tuple) and address and isinstance(address[0], str):
        return address[0]
    return None  # Unix sockets and other families carry no network host.


def _host_allowed(host: str) -> bool:
    """Match exact host names, or a suffix when the allowed entry starts with a dot."""
    host = host.lower().rstrip(".")
    return any(host == entry or (entry.startswith(".") and host.endswith(entry)) for entry in _allowed_hosts)


def _check(address: Any) -> None:
    host = _target_host(address)
    if host is None or is_local_address(host):
        return
    with _lock:
        allowed = host in _allowed_ips or _host_allowed(host)
    if not allowed:
        logger.warning("Blocked outbound connection to {}", host)
        raise OutboundConnectionBlocked(
            f"Outbound connection to {host} is not allowed by Pebbo's network guard."
        )


def _guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
    results = _original_getaddrinfo(host, *args, **kwargs)
    if isinstance(host, str):
        with _lock:
            if _host_allowed(host):
                _allowed_ips.update(str(entry[4][0]) for entry in results)
    return results


def _guarded_connect(self: socket.socket, address: Any) -> Any:
    _check(address)
    return _original_connect(self, address)


def _guarded_connect_ex(self: socket.socket, address: Any) -> Any:
    _check(address)
    return _original_connect_ex(self, address)


def _guarded_sendto(self: socket.socket, data: Any, *args: Any) -> Any:
    _check(args[-1] if args else None)
    return _original_sendto(self, data, *args)


if sys.platform == "win32":

    def _guarded_proactor_connect(self: Any, conn: socket.socket, address: Any) -> Any:
        _check(address)
        return _original_proactor_connect(self, conn, address)

    def _guarded_proactor_sendto(
        self: Any, conn: socket.socket, buf: Any, flags: int = 0, addr: Any = None
    ) -> Any:
        _check(addr)
        return _original_proactor_sendto(self, conn, buf, flags, addr)


def install(allowed_hosts: Iterable[str] = ()) -> None:
    """Install the guard for the whole process. Further hosts can be allowed later."""
    global _installed
    allow(allowed_hosts)
    with _lock:
        if _installed:
            return
        socket.getaddrinfo = _guarded_getaddrinfo
        socket.socket.connect = _guarded_connect  # type: ignore[method-assign,assignment]
        socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[method-assign,assignment]
        socket.socket.sendto = _guarded_sendto  # type: ignore[method-assign,assignment]
        if sys.platform == "win32":
            IocpProactor.connect = _guarded_proactor_connect  # type: ignore[method-assign]
            IocpProactor.sendto = _guarded_proactor_sendto  # type: ignore[method-assign]
        _installed = True


def allow(hosts: Iterable[str]) -> None:
    """Allow additional host names, for example while downloading models.

    An entry starting with a dot, such as ``.hf.co``, allows every subdomain.
    """
    with _lock:
        _allowed_hosts.update(host.lower() for host in hosts)


def revoke(hosts: Iterable[str]) -> None:
    """Withdraw previously allowed host names and the addresses they resolved to."""
    with _lock:
        for host in hosts:
            _allowed_hosts.discard(host.lower())
        _allowed_ips.clear()


def uninstall() -> None:
    """Remove the guard. Only meant for tests."""
    global _installed
    with _lock:
        socket.getaddrinfo = _original_getaddrinfo
        socket.socket.connect = _original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = _original_connect_ex  # type: ignore[method-assign]
        socket.socket.sendto = _original_sendto  # type: ignore[method-assign]
        if sys.platform == "win32":
            IocpProactor.connect = _original_proactor_connect  # type: ignore[method-assign]
            IocpProactor.sendto = _original_proactor_sendto  # type: ignore[method-assign]
        _allowed_hosts.clear()
        _allowed_ips.clear()
        _installed = False
