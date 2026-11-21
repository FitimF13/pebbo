"""Two Pebbos: pairing, handoffs only after approval, and no access to the other's data."""

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pebbo.app import create_app
from pebbo.instances.api import peer_router, register_handoff_tool
from pebbo.instances.peers import Peers
from pebbo.store import Store
from pebbo.tools.registry import ToolContext, ToolRegistry


class Network:
    """Routes calls between in-process instances by address, like a home network would."""

    def __init__(self) -> None:
        self.clients: dict[str, TestClient] = {}

    def send(self, url: str, body: dict[str, Any], token: str) -> dict[str, Any]:
        for address, client in self.clients.items():
            if url.startswith(address):
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                response = client.post(url[len(address) :], json=body, headers=headers)
                reply: dict[str, Any] = response.json()
                return reply
        raise OSError("unreachable")


def instance(network: Network, name: str, address: str) -> tuple[Store, Peers, TestClient]:
    store = Store(":memory:")
    peers = Peers(store, name, address, transport=network.send)
    client = TestClient(create_app(store=store, peers=peers))
    network.clients[address] = client
    return store, peers, client


@pytest.fixture
def pair() -> tuple[tuple[Store, Peers, TestClient], tuple[Store, Peers, TestClient]]:
    network = Network()
    home = instance(network, "Zuhause", "http://192.168.1.10:8100")
    office = instance(network, "Büro", "http://10.0.0.5:8100")
    home[0].add_person("Alex", "owner")
    office[0].add_person("Alex", "owner")
    code = home[2].post("/api/control/instances/invite").json()["code"]
    peer = office[2].post(
        "/api/control/instances/connect", json={"address": "http://192.168.1.10:8100", "code": code}
    )
    assert peer.status_code == 200 and peer.json()["name"] == "Zuhause"
    return home, office


def test_instances_pair_with_a_code(pair: Any) -> None:
    home, office = pair
    assert [p.name for p in home[1].peers()] == ["Büro"]
    assert [p.name for p in office[1].peers()] == ["Zuhause"]
    used = office[2].post(
        "/api/control/instances/connect", json={"address": "http://192.168.1.10:8100", "code": "000000"}
    )
    assert used.status_code == 400


def test_a_handoff_is_sent_only_after_approval(pair: Any) -> None:
    home, office = pair
    registry = ToolRegistry()
    register_handoff_tool(registry, office[1])
    alex = office[0].people()[0]
    result = asyncio.run(
        registry.call(
            "prepare_handoff",
            {"content": "Offerte für Müller morgen nachfassen"},
            ToolContext(office[0], alex),
        )
    )
    assert result.outcome == "prepared" and "Kontrollzentrum" in result.say
    assert home[0].reminders() == []

    pending = office[2].get("/api/control/instances").json()["handoffs"][0]
    assert pending["status"] == "pending"
    sent = office[2].post(f"/api/control/instances/handoffs/{pending['id']}", json={"approve": True}).json()
    assert sent["status"] == "sent"

    reminders = home[0].reminders(home[0].people()[0].id)
    assert [r.text for r in reminders] == ["Übergabe von Büro: Offerte für Müller morgen nachfassen"]
    assert home[2].get("/api/control/instances").json()["handoffs"][0]["direction"] == "in"


def test_a_rejected_handoff_never_arrives(pair: Any) -> None:
    home, office = pair
    handoff = office[1].prepare("Alex", "Geheim")
    rejected = office[2].post(f"/api/control/instances/handoffs/{handoff.id}", json={"approve": False}).json()
    assert rejected["status"] == "rejected"
    assert home[0].reminders() == [] and home[0].all_memories() == []
    again = office[2].post(f"/api/control/instances/handoffs/{handoff.id}", json={"approve": True})
    assert again.status_code == 400


def test_the_other_instance_cannot_read_and_unpairing_revokes_at_once(pair: Any) -> None:
    home, office = pair
    home[0].add_memory(home[0].people()[0].id, "fact", "Privat zuhause")
    peer_paths = {getattr(route, "path", "") for route in peer_router(home[1]).routes}
    assert peer_paths == {"/api/peer/pair", "/api/peer/handoff"}
    assert home[2].post("/api/peer/handoff", json={"person": "Alex", "content": "x"}).status_code == 401

    home_peer = home[1].peers()[0]
    assert home[2].delete(f"/api/control/instances/{home_peer.id}").status_code == 204
    handoff = office[1].prepare("Alex", "Nach dem Entkoppeln")
    assert office[1].decide(handoff.id, approve=True).status == "failed"


def test_peers_may_call_only_from_private_networks() -> None:
    from pebbo.access import allowed

    def scope(host: str, path: str) -> dict[str, object]:
        return {"type": "http", "client": (host, 50000), "path": path}

    assert allowed(scope("192.168.1.20", "/api/peer/handoff"))
    assert allowed(scope("100.64.3.4", "/api/peer/handoff"))  # Headscale / Tailscale
    assert not allowed(scope("8.8.8.8", "/api/peer/handoff"))
    assert not allowed(scope("100.64.3.4", "/api/control/instances"))


def test_guessing_pairing_codes_withdraws_the_invitation() -> None:
    from pebbo.instances.peers import MAX_FAILED_PAIRINGS, PeerError

    peers = Peers(Store(":memory:"), "Zuhause", "http://192.168.1.10:8100")
    code = peers.invite()
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(MAX_FAILED_PAIRINGS):
        with pytest.raises(PeerError):
            peers.accept(wrong, "Fremd", "http://192.168.1.66:8100", "x")
    with pytest.raises(PeerError):
        peers.accept(code, "Fremd", "http://192.168.1.66:8100", "x")
    assert peers.accept(peers.invite(), "Büro", "http://10.0.0.5:8100", "y")


def test_the_own_address_is_reachable_when_listening_on_all_interfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With PEBBO_HOST=0.0.0.0 the other instance was told "http://0.0.0.0:8120" and could not call back.
    from pebbo import phones
    from pebbo.config import ServerConfig

    monkeypatch.setattr(phones, "local_addresses", lambda: ["192.168.1.20", "172.24.0.1"])
    assert ServerConfig(host="0.0.0.0", port=8120, public_url="").own_address() == "http://192.168.1.20:8120"  # noqa: S104
    assert ServerConfig(host="127.0.0.1", port=8100, public_url="").own_address() == "http://127.0.0.1:8100"
    assert ServerConfig(host="0.0.0.0", port=8120, public_url="http://pebbo.lan:8120").own_address() == (  # noqa: S104
        "http://pebbo.lan:8120"
    )
    monkeypatch.setattr(phones, "local_addresses", lambda: [])
    assert ServerConfig(host="0.0.0.0", port=8120, public_url="").own_address() == "http://0.0.0.0:8120"  # noqa: S104
