"""Pebbo bodies: pairing with a code, the boot-time OTA answer and Opus audio."""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from pebbo.app import create_app
from pebbo.devices.opus import OpusDecoder, OpusEncoder
from pebbo.store import Store

BODY = {"Device-Id": "AA:BB:CC:00:11:22", "Client-Id": "6f1c7a52-0b8e-4a39-9d1e-0a1b2c3d4e5f"}
BOOT = {"application": {"version": "2.6.0"}, "board": {"name": "esp-box-3"}}


@pytest.fixture
def store() -> Store:
    return Store(":memory:")


def test_a_body_pairs_with_the_code_on_its_screen(store: Store) -> None:
    client = TestClient(create_app(store=store))

    first = client.post("/xiaozhi/ota/", json=BOOT, headers=BODY).json()
    code = first["activation"]["code"]
    assert len(code) == 6 and "websocket" not in first and "mqtt" not in first
    assert first["firmware"] == {"version": "2.6.0", "url": ""}
    assert client.post("/xiaozhi/ota/", json=BOOT, headers=BODY).json()["activation"]["code"] == code
    assert client.post("/xiaozhi/ota/activate", json={}, headers=BODY).status_code == 202

    assert (
        client.post(
            "/api/control/devices/pair", json={"code": "000000" if code != "000000" else "111111"}
        ).status_code
        == 404
    )
    paired = client.post("/api/control/devices/pair", json={"code": code}).json()
    assert paired["status"] == "paired" and paired["board"] == "esp-box-3" and not paired["online"]
    assert client.post("/xiaozhi/ota/activate", json={}, headers=BODY).status_code == 200

    reply = client.post("/xiaozhi/ota/", json=BOOT, headers=BODY).json()
    assert "activation" not in reply and "mqtt" not in reply
    assert reply["websocket"]["url"] == "ws://testserver:80/xiaozhi/v1/"
    assert reply["websocket"]["token"] == store.devices()[0].token
    assert reply["server_time"]["timestamp"] > 0


def test_a_removed_body_must_pair_again(store: Store) -> None:
    client = TestClient(create_app(store=store))
    code = client.post("/xiaozhi/ota/", json=BOOT, headers=BODY).json()["activation"]["code"]
    device = client.post("/api/control/devices/pair", json={"code": code}).json()

    assert (
        client.patch(f"/api/control/devices/{device['id']}", json={"name": "Büro"}).json()["name"] == "Büro"
    )
    assert client.delete(f"/api/control/devices/{device['id']}").status_code == 204
    assert "activation" in client.post("/xiaozhi/ota/", json=BOOT, headers=BODY).json()
    assert client.get("/api/control/devices").json()[0]["status"] == "pending"


def test_requests_without_identity_are_refused(store: Store) -> None:
    client = TestClient(create_app(store=store))
    assert client.post("/xiaozhi/ota/", json=BOOT).status_code == 400


def test_expired_codes_do_not_pair(store: Store) -> None:
    store.request_pairing("aa", "bb", "box", "123456", expires_at=1.0)
    assert store.pair_device("123456", "token") is None


def test_opus_round_trip_keeps_the_signal() -> None:
    rate = 24_000
    tone = (np.sin(np.arange(rate) / rate * 2 * np.pi * 440) * 8000).astype(np.int16)
    encoder, decoder = OpusEncoder(rate), OpusDecoder(16_000)

    packets = []
    for start in range(0, len(tone), 1000):
        packets += encoder.encode(tone[start : start + 1000].tobytes())
    packets += encoder.flush()
    pcm = np.frombuffer(b"".join(decoder.decode(packet) for packet in packets), dtype=np.int16)

    assert len(packets) == 17
    assert abs(len(pcm) - 16_000 * 17 * 0.06) < 200
    assert np.abs(pcm[4000:8000]).max() > 4000
    decoder.decode(b"\x00garbage")  # A broken packet is skipped, not raised.


def test_only_bodies_may_connect_from_the_home_network() -> None:
    from pebbo.access import allowed

    def scope(host: str, path: str) -> dict[str, object]:
        return {"type": "http", "client": (host, 50000), "path": path}

    assert allowed(scope("127.0.0.1", "/api/control/people"))
    assert allowed(scope("::1", "/"))
    assert allowed(scope("192.168.1.40", "/xiaozhi/ota/"))
    assert allowed(scope("10.0.0.7", "/xiaozhi/v1/"))
    assert not allowed(scope("192.168.1.40", "/api/control/people"))
    assert not allowed(scope("192.168.1.40", "/"))
    assert not allowed(scope("8.8.8.8", "/xiaozhi/ota/"))
    assert not allowed(scope("169.254.1.1", "/xiaozhi/ota/"))


def test_foreign_web_pages_cannot_use_the_control_centre() -> None:
    from pebbo.access import allowed

    def scope(path: str, **headers: str) -> dict[str, object]:
        raw = [(key.encode(), value.encode()) for key, value in headers.items()]
        return {"type": "http", "client": ("127.0.0.1", 50000), "path": path, "headers": raw}

    assert allowed(scope("/api/control/people", host="127.0.0.1:8100", origin="http://127.0.0.1:8100"))
    assert allowed(scope("/api/control/people", host="localhost:5173", origin="http://localhost:5173"))
    assert allowed(scope("/api/offer", host="[::1]:8100"))
    # Cross-site request forgery from a page on another site.
    assert not allowed(scope("/api/control/people", host="127.0.0.1:8100", origin="https://evil.example"))
    # DNS rebinding: a foreign name that resolves to this computer.
    assert not allowed(scope("/api/control/people", host="evil.example:8100"))
    # A browser page must not pose as a body or another instance.
    assert not allowed(scope("/xiaozhi/ota/", host="127.0.0.1:8100", origin="http://127.0.0.1:8100"))
    assert allowed(scope("/xiaozhi/ota/", host="192.168.1.10:8100"))
