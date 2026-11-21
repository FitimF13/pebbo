"""The model router: Pebbo thinks on the best reachable computer and falls back when it goes away."""

import pytest
from fastapi.testclient import TestClient

from pebbo.compute_api import compute_router
from pebbo.models_router import ComputeDevice, ModelRouter
from pebbo.store import Store
from pebbo.voice.models import speech_model

THIS_PC = ComputeDevice(0, "Dieser Rechner", "http://127.0.0.1:11434/v1", "pebbo-ministral", 0)


class FakeNetwork:
    def __init__(self) -> None:
        self.up: set[str] = set()

    def check(self, base_url: str, model: str) -> bool:
        return f"{base_url}|{model}" in self.up


@pytest.fixture
def router() -> tuple[ModelRouter, FakeNetwork]:
    network = FakeNetwork()
    return ModelRouter(Store(":memory:"), THIS_PC, check=network.check), network


def test_the_first_reachable_device_in_the_owners_order_wins(router: tuple[ModelRouter, FakeNetwork]) -> None:
    pebbo, network = router
    gaming = pebbo.add("Gaming-PC", "http://192.168.1.30:11434/v1", "pebbo-ministral")
    box = pebbo.add("Mini-PC", "http://192.168.1.40:11434/v1", "qwen3:1.7b")
    pebbo.move(gaming.id, 0)
    pebbo.move(THIS_PC.id, 9)

    network.up = {f"{box.base_url}|{box.model}", f"{gaming.base_url}|{gaming.model}"}
    pebbo.refresh()
    assert pebbo.current().name in {"Gaming-PC", "Dieser Rechner"}

    network.up = {f"{box.base_url}|{box.model}"}
    pebbo.refresh()
    assert pebbo.current().name == "Mini-PC"

    network.up = set()
    pebbo.refresh()
    assert pebbo.current() == THIS_PC


def test_devices_must_be_on_the_home_network(router: tuple[ModelRouter, FakeNetwork]) -> None:
    pebbo, _ = router
    with pytest.raises(ValueError):
        pebbo.add("Cloud", "http://8.8.8.8:11434/v1", "x")
    with pytest.raises(ValueError):
        pebbo.add("Kaputt", "ftp://192.168.1.2", "x")
    assert pebbo.add("VPN", "http://100.70.1.2:11434/v1", "x").name == "VPN"


def test_the_control_centre_lists_adds_and_removes_devices(router: tuple[ModelRouter, FakeNetwork]) -> None:
    from fastapi import FastAPI

    pebbo, network = router
    app = FastAPI()
    app.include_router(compute_router(pebbo))
    client = TestClient(app)

    added = client.post(
        "/api/control/compute",
        json={"name": "Mini-PC", "base_url": "http://192.168.1.40:11434/v1", "model": "qwen3:1.7b"},
    )
    assert added.status_code == 201 and added.json()["reachable"] is False
    network.up = {"http://192.168.1.40:11434/v1|qwen3:1.7b"}
    listed = client.post("/api/control/compute/check").json()
    assert [d["name"] for d in listed] == ["Dieser Rechner", "Mini-PC"]
    assert listed[1]["active"] is True and listed[0]["removable"] is False
    assert client.delete("/api/control/compute/0").status_code == 404
    assert client.delete(f"/api/control/compute/{listed[1]['id']}").status_code == 204


def test_without_a_gpu_speech_recognition_uses_a_small_model_on_the_cpu() -> None:
    assert speech_model("large-v3-turbo", "cpu", "int8_float16", "small") == ("small", "cpu", "int8")
    assert speech_model("large-v3-turbo", "cuda", "int8_float16", "small") == (
        "large-v3-turbo",
        "cuda",
        "int8_float16",
    )
