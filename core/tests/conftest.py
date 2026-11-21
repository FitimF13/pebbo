"""Test-wide network rules that pytest-socket does not cover on its own.

pytest-socket patches ``socket.socket.connect``. On Windows, asyncio's event loop connects
and sends datagrams through the IOCP proactor instead, so those calls are limited to
loopback here as well.
"""

import ipaddress
import sys
from typing import Any

from pytest_socket import SocketConnectBlockedError


def _loopback_only(address: Any) -> None:
    host = address[0] if isinstance(address, tuple) and address else None
    if host is None:
        return
    try:
        if ipaddress.ip_address(str(host).split("%", 1)[0]).is_loopback:
            return
    except ValueError:
        pass
    raise SocketConnectBlockedError(["127.0.0.1", "::1"], str(host))


if sys.platform == "win32":
    from asyncio.windows_events import IocpProactor

    _connect = IocpProactor.connect
    _sendto = IocpProactor.sendto

    def _guarded_connect(self: Any, conn: Any, address: Any) -> Any:
        _loopback_only(address)
        return _connect(self, conn, address)

    def _guarded_sendto(self: Any, conn: Any, buf: Any, flags: int = 0, addr: Any = None) -> Any:
        _loopback_only(addr)
        return _sendto(self, conn, buf, flags, addr)

    IocpProactor.connect = _guarded_connect  # type: ignore[method-assign]
    IocpProactor.sendto = _guarded_sendto  # type: ignore[method-assign]
