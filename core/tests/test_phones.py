"""Paired phones: pairing, tokens, revocation, network access and the app API with text chat."""

import sqlite3
import time
import urllib.error
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pebbo import clock, phones
from pebbo.access import allowed
from pebbo.app import create_app
from pebbo.config import ServerConfig
from pebbo.store import Store
from pebbo.voice import assistant


@pytest.fixture
def store(tmp_path: Any) -> Store:
    return Store(tmp_path / "pebbo.sqlite3")


@pytest.fixture(autouse=True)
def home_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PEBBO_HOST", "0.0.0.0")  # noqa: S104 - only read, nothing binds
    monkeypatch.delenv("PEBBO_APP_ADDRESS", raising=False)
    monkeypatch.setattr(phones, "local_addresses", lambda: ["192.168.1.20"])


def pair(client: TestClient, person_id: int, name: str = "Testhandy") -> dict[str, Any]:
    pairing = client.post("/api/control/phones/pairings", json={"person_id": person_id}).json()
    reply = client.post("/api/app/pair", json={"code": pairing["code"], "name": name})
    assert reply.status_code == 200, reply.text
    result: dict[str, Any] = reply.json()
    return result


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_a_phone_pairs_once_with_the_code_and_gets_its_own_token(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    client = TestClient(create_app(store=store))

    pairing = client.post("/api/control/phones/pairings", json={"person_id": alex.id}).json()
    assert len(pairing["code"]) == 6 and pairing["code"].isdigit()
    assert pairing["addresses"] == ["http://192.168.1.20:8100"] and pairing["reachable"] is True
    listed = client.get("/api/control/phones").json()
    assert listed["pairings"][0]["id"] == pairing["id"] and "code" not in listed["pairings"][0]

    paired = client.post("/api/app/pair", json={"code": pairing["code"], "name": "Alex' iPhone"})
    assert paired.status_code == 200
    body = paired.json()
    assert body["person"] == {"id": alex.id, "name": "Alex", "role": "owner"}
    assert body["phone"]["name"] == "Alex' iPhone" and len(body["token"]) >= 40
    again = client.post("/api/app/pair", json={"code": pairing["code"], "name": "Zweites"})
    assert again.status_code == 404

    listed = client.get("/api/control/phones").json()
    assert listed["pairings"] == [] and listed["phones"][0]["person_id"] == alex.id
    me = client.get("/api/app/me", headers=bearer(body["token"])).json()
    assert me["person"]["name"] == "Alex" and me["phone"]["id"] == body["phone"]["id"]


def test_only_hashes_of_tokens_and_codes_are_stored(store: Store, tmp_path: Any) -> None:
    alex = store.add_person("Alex", "owner")
    client = TestClient(create_app(store=store))
    pairing = client.post("/api/control/phones/pairings", json={"person_id": alex.id}).json()
    code = pairing["code"]

    with sqlite3.connect(tmp_path / "pebbo.sqlite3") as db:
        assert code not in str(db.execute("SELECT * FROM phone_pairings").fetchall())
    token = client.post("/api/app/pair", json={"code": code}).json()["token"]
    with sqlite3.connect(tmp_path / "pebbo.sqlite3") as db:
        rows = str(db.execute("SELECT * FROM phones").fetchall())
    assert token not in rows and phones.token_hash(token) in rows


def test_requests_without_a_valid_token_are_refused(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    client = TestClient(create_app(store=store))
    token = pair(client, alex.id)["token"]

    assert client.get("/api/app/me").status_code == 401
    assert client.get("/api/app/me", headers=bearer("falsch")).status_code == 401
    assert client.get("/api/app/me", headers={"Authorization": token}).status_code == 401
    assert client.get("/api/app/memories", headers=bearer(token + "x")).status_code == 401
    assert client.get("/api/app/me", headers=bearer(token)).status_code == 200


def test_removing_a_phone_ends_its_access_at_once(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    sara = store.add_person("Sara", "adult")
    client = TestClient(create_app(store=store))
    first = pair(client, alex.id)
    second = pair(client, alex.id)
    third = pair(client, sara.id)

    assert client.delete(f"/api/control/phones/{first['phone']['id']}").status_code == 204
    assert client.get("/api/app/me", headers=bearer(first["token"])).status_code == 401
    assert client.get("/api/app/me", headers=bearer(second["token"])).status_code == 200

    assert client.delete("/api/app/me", headers=bearer(second["token"])).status_code == 204
    assert client.get("/api/app/me", headers=bearer(second["token"])).status_code == 401

    client.delete(f"/api/control/people/{sara.id}")
    assert client.get("/api/app/me", headers=bearer(third["token"])).status_code == 401
    assert store.phones() == []


def test_wrong_codes_end_open_pairings(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    client = TestClient(create_app(store=store))
    code = client.post("/api/control/phones/pairings", json={"person_id": alex.id}).json()["code"]
    wrong = [f"{(int(code) + n) % 1_000_000:06d}" for n in range(1, phones.MAX_FAILED_ATTEMPTS + 1)]

    for guess in wrong:
        assert client.post("/api/app/pair", json={"code": guess}).status_code == 404
    assert client.post("/api/app/pair", json={"code": code}).status_code == 404
    assert client.post("/api/app/pair", json={"code": "12ab56"}).status_code == 422


def test_expired_codes_and_unknown_people_are_refused(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    alex = store.add_person("Alex", "owner")
    client = TestClient(create_app(store=store))
    assert client.post("/api/control/phones/pairings", json={"person_id": 99}).status_code == 404

    monkeypatch.setattr(phones, "PAIRING_SECONDS", -1)
    code = client.post("/api/control/phones/pairings", json={"person_id": alex.id}).json()["code"]
    assert client.post("/api/app/pair", json={"code": code}).status_code == 404

    monkeypatch.setattr(phones, "PAIRING_SECONDS", 600)
    pairing = client.post("/api/control/phones/pairings", json={"person_id": alex.id}).json()
    assert client.delete(f"/api/control/phones/pairings/{pairing['id']}").status_code == 204
    assert client.post("/api/app/pair", json={"code": pairing["code"]}).status_code == 404


def test_pairing_tells_when_phones_cannot_reach_the_core(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PEBBO_HOST", "127.0.0.1")
    addresses, reachable = phones.app_addresses(ServerConfig())
    assert addresses == ["http://192.168.1.20:8100"] and not reachable

    monkeypatch.setenv("PEBBO_HOST", "192.168.1.30")
    assert phones.app_addresses(ServerConfig()) == (["http://192.168.1.30:8100"], True)

    monkeypatch.setenv("PEBBO_APP_ADDRESS", "http://pebbo.local:8100/")
    assert phones.app_addresses(ServerConfig()) == (["http://pebbo.local:8100"], True)


def scope(host: str, path: str) -> dict[str, Any]:
    return {"type": "http", "client": (host, 50000), "path": path}


def test_the_app_api_answers_on_the_home_network_but_the_control_centre_does_not() -> None:
    assert allowed(scope("192.168.1.40", "/api/app/me"))
    assert allowed(scope("10.0.0.7", "/api/app/pair"))
    assert allowed(scope("fd00::12", "/api/app/chat"))
    assert not allowed(scope("8.8.8.8", "/api/app/me"))
    assert not allowed(scope("169.254.1.1", "/api/app/me"))
    assert not allowed(scope("192.168.1.40", "/api/control/phones"))
    assert not allowed(scope("192.168.1.40", "/api/control/phones/pairings"))
    assert not allowed(scope("192.168.1.40", "/api/app/../control/people"))
    assert not allowed(scope("192.168.1.40", "/api/app/./../../index.html"))
    assert not allowed(scope("192.168.1.40", "/api/apps"))
    assert not allowed(scope("192.168.1.40", "/"))


def test_browser_pages_cannot_speak_for_a_phone() -> None:
    page = {**scope("192.168.1.40", "/api/app/pair"), "headers": [(b"origin", b"http://evil.example")]}
    assert not allowed(page)
    local_page = {**scope("127.0.0.1", "/api/app/pair"), "headers": [(b"origin", b"http://evil.example")]}
    assert not allowed(local_page)
    # An emulator reaches the computer's loopback under another host name, for example 10.0.2.2.
    emulator = {**scope("127.0.0.1", "/api/app/me"), "headers": [(b"host", b"10.0.2.2:8100")]}
    assert allowed(emulator)
    assert not allowed({**emulator, "path": "/api/control/people"})


def test_the_access_policy_holds_for_real_requests(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    local = TestClient(create_app(store=store))
    token = pair(local, alex.id)["token"]
    phone = TestClient(create_app(store=store), client=("192.168.1.40", 50000))
    outside = TestClient(create_app(store=store), client=("8.8.8.8", 50000))

    assert phone.get("/api/app/me", headers=bearer(token)).status_code == 200
    assert phone.get("/api/control/people").status_code == 403
    assert phone.post("/api/control/phones/pairings", json={"person_id": alex.id}).status_code == 403
    assert outside.get("/api/app/me", headers=bearer(token)).status_code == 403


def test_a_phone_sees_and_changes_only_its_own_persons_data(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    sara = store.add_person("Sara", "adult")
    alex_fact = store.add_memory(alex.id, "fact", "Mag Kaffee ohne Zucker")
    sara_fact = store.add_memory(sara.id, "fact", "Spielt Tennis")
    store.add_memory(None, "fact", "Der Ersatzschlüssel liegt in der Schublade")
    alex_reminder = store.add_reminder(alex.id, "Zahnarzt", time.time() + 3600)
    sara_reminder = store.add_reminder(sara.id, "Training", time.time() + 3600)
    client = TestClient(create_app(store=store))
    token = pair(client, sara.id)["token"]

    memories = client.get("/api/app/memories", headers=bearer(token)).json()
    assert [m["text"] for m in memories] == ["Spielt Tennis"]
    reminders = client.get("/api/app/reminders", headers=bearer(token)).json()
    assert [r["text"] for r in reminders] == ["Training"] and reminders[0]["due_text"]

    assert client.delete(f"/api/app/memories/{alex_fact.id}", headers=bearer(token)).status_code == 404
    assert client.delete(f"/api/app/reminders/{alex_reminder.id}", headers=bearer(token)).status_code == 404
    assert store.memory_by_id(alex_fact.id) is not None and len(store.reminders(alex.id)) == 1

    assert client.delete(f"/api/app/memories/{sara_fact.id}", headers=bearer(token)).status_code == 204
    assert client.delete(f"/api/app/reminders/{sara_reminder.id}", headers=bearer(token)).status_code == 204
    assert store.memories(sara.id) == [] and store.reminders(sara.id) == []


class FakeModel:
    """Stands in for Ollama: the answer model and the action agent."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.answers: list[str] = []
        self.actions: list[list[tuple[str, dict[str, Any]]]] = []
        self.prompts: list[list[dict[str, Any]]] = []
        self.decided: list[list[dict[str, Any]]] = []

        def complete(_base_url: str, _model: str, messages: list[dict[str, Any]]) -> str:
            self.prompts.append(messages)
            if not self.answers:
                raise urllib.error.URLError("no model")
            return self.answers.pop(0)

        def choose_actions(
            _base_url: str, _model: str, _tools: Any, messages: Any, *_known: Any
        ) -> list[tuple[str, dict[str, Any]]]:
            self.decided.append(list(messages))
            return self.actions.pop(0) if self.actions else []

        monkeypatch.setattr("pebbo.chat.complete", complete)
        monkeypatch.setattr(assistant, "choose_actions", choose_actions)


def test_chat_answers_as_pebbo_and_acts_through_the_tools(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = FakeModel(monkeypatch)
    alex = store.add_person("Alex", "owner")
    sara = store.add_person("Sara", "adult")
    store.add_memory(alex.id, "fact", "Mag Kaffee ohne Zucker")
    store.add_memory(sara.id, "fact", "Spielt Tennis")
    client = TestClient(create_app(store=store))
    token = pair(client, sara.id)["token"]

    model.answers.append("[happy] Gern! Hab ich mir gemerkt.")
    model.actions.append([("remember", {"text": "Trinkt gern Pfefferminztee", "explicit": True})])
    reply = client.post(
        "/api/app/chat", json={"text": "Merk dir, ich trinke gern Pfefferminztee"}, headers=bearer(token)
    )

    assert reply.status_code == 200
    assert reply.json() == {
        "answer": "Gern!",
        "emotion": "happy",
        "actions": ["Hab ich mir gemerkt: Trinkt gern Pfefferminztee."],
    }
    assert store.memories(sara.id)[0].text == "Trinkt gern Pfefferminztee"
    system = model.prompts[0][0]
    assert system["role"] == "system" and "Du bist Pebbo" in system["content"]
    assert "Sara" in system["content"] and "Pebbo-App" in system["content"]
    assert "Spielt Tennis" in system["content"] and "Kaffee" not in system["content"]

    model.answers.append("[curious] Klar, um sieben.")
    tomorrow = (datetime.now(clock.timezone()) + timedelta(days=1)).strftime("%Y-%m-%dT07:00")
    model.actions.append([("set_reminder", {"text": "Tee", "due": tomorrow})])
    second = client.post(
        "/api/app/chat", json={"text": "Erinnere mich dann an Tee"}, headers=bearer(token)
    ).json()
    assert second["emotion"] == "curious" and second["actions"][0].startswith("Ich erinnere dich")
    assert [r.text for r in store.reminders(sara.id)] == ["Tee"]
    history = [m["content"] for m in model.decided[1]]
    assert (
        history[0] == "Merk dir, ich trinke gern Pfefferminztee"
        and history[-1] == "Erinnere mich dann an Tee"
    )
    assert "Hab ich mir gemerkt" in history[1]


def test_chat_answers_without_stage_directions_or_markup(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Seen with the real model: "Gern! *Das System hat deine Präferenz gespeichert.*"
    model = FakeModel(monkeypatch)
    alex = store.add_person("Alex", "owner")
    client = TestClient(create_app(store=store))
    token = pair(client, alex.id)["token"]

    model.answers.append("[neutral] Gern! *Das System hat die Erinnerung geplant.* Bis **morgen** 😊 [happy]")
    reply = client.post("/api/app/chat", json={"text": "Danke"}, headers=bearer(token)).json()
    assert reply["answer"] == "Gern! Bis morgen"

    # The confirmation is shown once, under the answer, not also inside it.
    model.answers.append("[happy] Mach ich! Hab ich mir gemerkt: Mag Tee.")
    model.actions.append([("remember", {"text": "Mag Tee", "explicit": True})])
    reply = client.post("/api/app/chat", json={"text": "Merk dir: Tee"}, headers=bearer(token)).json()
    assert reply["answer"] == "Mach ich!" and reply["actions"] == ["Hab ich mir gemerkt: Mag Tee."]


def test_a_tool_that_answers_the_question_replaces_the_guessed_answer(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Seen with the real model: "Ich weiss es nicht. Soll ich nachschauen?" above
    # "Morgen hast du keine Termine." The model answers before the calendar was read.
    model = FakeModel(monkeypatch)
    alex = store.add_person("Alex", "owner")
    client = TestClient(create_app(store=store))
    token = pair(client, alex.id)["token"]

    model.answers.append("[curious] Ich weiss es nicht. Soll ich nachschauen?")
    model.actions.append([("list_events", {"day": "morgen"})])
    reply = client.post("/api/app/chat", json={"text": "Was habe ich morgen?"}, headers=bearer(token)).json()
    assert reply == {"answer": "Morgen hast du keine Termine.", "emotion": "curious", "actions": []}


def test_chat_history_is_short_and_per_phone(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    model = FakeModel(monkeypatch)
    alex = store.add_person("Alex", "owner")
    client = TestClient(create_app(store=store))
    first, second = pair(client, alex.id)["token"], pair(client, alex.id)["token"]

    for n in range(8):
        model.answers.append(f"[neutral] Antwort {n}.")
        client.post("/api/app/chat", json={"text": f"Frage {n}"}, headers=bearer(first))
    model.answers.append("[neutral] Hoi.")
    client.post("/api/app/chat", json={"text": "Hallo"}, headers=bearer(second))

    long_prompt = [m["content"] for m in model.prompts[7][1:]]
    assert len(long_prompt) == 11 and long_prompt[0] == "Frage 2" and long_prompt[-1] == "Frage 7"
    assert [m["content"] for m in model.prompts[8][1:]] == ["Hallo"]


def test_chat_reports_when_the_model_is_not_running(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    FakeModel(monkeypatch)
    alex = store.add_person("Alex", "owner")
    client = TestClient(create_app(store=store))
    token = pair(client, alex.id)["token"]

    reply = client.post("/api/app/chat", json={"text": "Hallo"}, headers=bearer(token))
    assert reply.status_code == 503 and "Ollama" in reply.json()["detail"]
    assert client.post("/api/app/chat", json={"text": ""}, headers=bearer(token)).status_code == 422


def test_due_reminders_wait_for_the_app_until_it_acknowledges_them(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    sara = store.add_person("Sara", "adult")
    client = TestClient(create_app(store=store))
    token = pair(client, alex.id)["token"]
    phone = store.phones()[0]
    store.add_reminder(alex.id, "Von früher", phone.created_at - 10)
    due = store.add_reminder(alex.id, "Paket mitnehmen", phone.created_at + 0.001)
    store.add_reminder(alex.id, "Später", time.time() + 3600)
    store.add_reminder(sara.id, "Nicht meins", phone.created_at + 0.001)

    pending = client.get("/api/app/notifications", headers=bearer(token)).json()
    assert [(n["id"], n["kind"], n["text"]) for n in pending] == [(due.id, "reminder", "Paket mitnehmen")]
    acknowledged = client.post(
        "/api/app/notifications/ack", json={"until": time.time()}, headers=bearer(token)
    )
    assert acknowledged.status_code == 204
    assert client.get("/api/app/notifications", headers=bearer(token)).json() == []
    reminder = store.reminder_by_id(due.id)
    assert reminder is not None and reminder.status == "delivered"
    assert [r.text for r in store.reminders(sara.id)] == ["Nicht meins"]


def test_the_chat_model_must_be_at_home() -> None:
    from pebbo.chat import complete

    with pytest.raises(ValueError, match="home network"):
        complete("http://8.8.8.8:11434/v1", "pebbo-ministral", [])
    with pytest.raises(ValueError, match="home network"):
        complete("file:///etc/passwd", "pebbo-ministral", [])
