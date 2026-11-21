"""The test suite must never reach the network beyond loopback."""

import socket

import pytest
from pytest_socket import SocketConnectBlockedError


def test_outbound_connections_are_blocked() -> None:
    with (
        pytest.raises(SocketConnectBlockedError),
        socket.create_connection(("192.0.2.1", 443), timeout=1),
    ):
        pass


def test_asyncio_connections_are_blocked_too() -> None:
    import asyncio

    async def connect() -> None:
        await asyncio.open_connection("192.0.2.1", 443)

    with pytest.raises(SocketConnectBlockedError):
        asyncio.run(connect())
