"""The runtime network guard blocks public hosts unless they are allowed."""

import asyncio
import socket
from collections.abc import Iterator

import pytest

from pebbo import netguard


@pytest.fixture(autouse=True)
def guard() -> Iterator[None]:
    netguard.install()
    yield
    netguard.uninstall()


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "::1",
        "192.168.1.20",
        "10.0.0.5",
        "172.16.3.4",
        "fe80::1",
        "100.105.37.37",
        "fd7a:115c:a1e0::1",
    ],
)
def test_local_addresses_are_local(address: str) -> None:
    assert netguard.is_local_address(address)


@pytest.mark.parametrize("address", ["8.8.8.8", "142.250.1.1", "2001:4860:4860::8888", "not-an-ip"])
def test_public_addresses_are_not_local(address: str) -> None:
    assert not netguard.is_local_address(address)


def test_blocks_tcp_connections_to_public_addresses() -> None:
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection,
        pytest.raises(netguard.OutboundConnectionBlocked),
    ):
        connection.connect(("8.8.8.8", 443))


def test_blocks_udp_datagrams_to_public_addresses() -> None:
    # A public STUN server is exactly what WebRTC libraries contact by default.
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as datagram,
        pytest.raises(netguard.OutboundConnectionBlocked),
    ):
        datagram.sendto(b"stun", ("74.125.250.129", 19302))


def test_allows_loopback() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as datagram:
        datagram.sendto(b"local", ("127.0.0.1", 9))


def test_allowed_host_names_cover_their_subdomains() -> None:
    netguard.allow([".hf.co"])
    assert netguard._host_allowed("cas-bridge.xethub.hf.co")
    assert not netguard._host_allowed("hf.co.evil.example")
    netguard.revoke([".hf.co"])
    assert not netguard._host_allowed("cas-bridge.xethub.hf.co")


def test_blocks_asyncio_connections_to_public_addresses() -> None:
    # On Windows the event loop connects through the IOCP proactor, not socket.connect.
    async def connect() -> None:
        await asyncio.open_connection("8.8.8.8", 443)

    with pytest.raises(netguard.OutboundConnectionBlocked):
        asyncio.run(connect())


def test_blocks_asyncio_datagrams_to_public_addresses() -> None:
    # aiortc sends its STUN and media packets through a datagram transport.
    errors: list[Exception] = []

    class Recorder(asyncio.DatagramProtocol):
        def error_received(self, exc: Exception) -> None:
            errors.append(exc)

    async def send() -> None:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(Recorder, local_addr=("127.0.0.1", 0))
        try:
            transport.sendto(b"stun", ("74.125.250.129", 19302))
            await asyncio.sleep(0.05)
        finally:
            transport.close()

    try:
        asyncio.run(send())
    except netguard.OutboundConnectionBlocked:
        return
    assert any(isinstance(error, netguard.OutboundConnectionBlocked) for error in errors)
