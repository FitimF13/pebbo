"""The per-turn context and the control centre API."""

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pipecat.processors.aggregators.llm_context import LLMContext

from pebbo.app import create_app
from pebbo.store import Store
from pebbo.voice.assistant import CONTEXT_MARKER, context_message, conversation_messages, refresh
from pebbo.voice.session import ConversationState
from pebbo.voice.summary import transcript, user_turns


@pytest.fixture
def store() -> Store:
    return Store(":memory:")


def test_context_hides_personal_data_from_guests(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    store.add_memory(alex.id, "fact", "Mag Kaffee ohne Zucker")
    store.add_memory(None, "fact", "Der Ersatzschlüssel liegt in der Schublade")
    state = ConversationState(store, recognizer=None)

    guest = context_message(state)
    assert "Gast" in guest and "Kaffee" not in guest and "Ersatzschlüssel" not in guest
    state.person = alex
    known = context_message(state)
    assert "Alex" in known and "Kaffee" in known and "Ersatzschlüssel" in known


def test_context_speaks_about_the_speaker_in_the_second_person(store: Store) -> None:
    # Ministral answered "Ich bin's, Sara!" to "Weisst du, wer ich bin?" and talked about its own
    # coffee when asked "Wie trinke ich meinen Kaffee?".
    alex = store.add_person("Alex", "owner")
    store.add_memory(alex.id, "fact", "Mag Kaffee ohne Zucker")
    state = ConversationState(store, recognizer=None)

    assert "Du bist" not in context_message(state)
    state.person = alex
    known = context_message(state)
    assert "meint Alex sich selbst, nicht dich" in known and '"Du bist Alex"' in known
    assert "in der Du-Form" in known


def test_context_message_is_replaced_not_stacked() -> None:
    context = LLMContext(messages=[{"role": "user", "content": "Hallo"}])

    refresh(context, f"{CONTEXT_MARKER} eins")
    refresh(context, f"{CONTEXT_MARKER} zwei")

    messages = context.get_messages()
    assert len(messages) == 2 and "zwei" in str(messages[0])
    assert conversation_messages(context) == [{"role": "user", "content": "Hallo"}]


def test_transcript_for_summaries() -> None:
    messages = [
        {"role": "system", "content": "x"},
        {"role": "user", "content": "Ich gehe morgen wandern"},
        {"role": "assistant", "content": "Viel Spass!"},
    ]

    assert user_turns(messages) == 1
    assert transcript(messages, "Alex") == "Alex: Ich gehe morgen wandern\nPebbo: Viel Spass!"


def test_control_api_manages_people_memories_reminders_and_claims(store: Store) -> None:
    client = TestClient(create_app(store=store))

    assert client.post("/api/control/people", json={"name": "Sara", "role": "adult"}).status_code == 400
    owner = client.post("/api/control/people", json={"name": "Alex", "role": "owner"}).json()
    sara = client.post("/api/control/people", json={"name": "Sara", "role": "adult"}).json()
    assert client.delete(f"/api/control/people/{owner['id']}").status_code == 400

    memory = client.post(
        "/api/control/memories", json={"person_id": sara["id"], "text": "Spielt Tennis"}
    ).json()
    assert (
        client.patch(f"/api/control/memories/{memory['id']}", json={"text": "Spielt Squash"}).status_code
        == 204
    )
    assert client.get("/api/control/memories").json()[0]["text"] == "Spielt Squash"
    assert client.delete(f"/api/control/memories/{memory['id']}").status_code == 204

    reminder = store.add_reminder(sara["id"], "Training", 4_102_444_800)
    assert client.get("/api/control/reminders").json()[0]["due_text"]
    assert client.delete(f"/api/control/reminders/{reminder.id}").status_code == 204

    claim = store.add_voice_claim("Sara", np.ones(8, dtype=np.float32))
    assert client.get("/api/control/voice-claims").json()[0]["person_id"] == sara["id"]
    confirmed = client.post(f"/api/control/voice-claims/{claim.id}/confirm", json={"person_id": sara["id"]})
    assert confirmed.status_code == 204
    assert client.get("/api/control/people").json()[1]["voice_samples"] == 1
    assert client.delete(f"/api/control/people/{sara['id']}/voice").status_code == 204
    assert client.get("/api/control/people").json()[1]["voice_samples"] == 0


def test_people_have_distinct_names_and_german_errors(store: Store) -> None:
    # Names match voices, introductions and handoffs, so "Sara" and "sara" would be ambiguous.
    client = TestClient(create_app(store=store))
    client.post("/api/control/people", json={"name": "Alex", "role": "owner"})
    sara = client.post("/api/control/people", json={"name": "Sara", "role": "adult"}).json()

    second_owner = client.post("/api/control/people", json={"name": "Robin", "role": "owner"})
    assert (
        second_owner.status_code == 400 and second_owner.json()["detail"] == "Es gibt schon einen Besitzer."
    )
    twin = client.post("/api/control/people", json={"name": " sara ", "role": "child"})
    assert twin.status_code == 400 and twin.json()["detail"] == "Es gibt schon jemanden namens sara."
    blank = client.post("/api/control/people", json={"name": "  ", "role": "adult"})
    assert blank.status_code == 400 and blank.json()["detail"] == "Gib einen Namen ein."
    renamed = client.patch(f"/api/control/people/{sara['id']}", json={"name": "ALEX"})
    assert renamed.status_code == 400 and "ALEX" in renamed.json()["detail"]
    assert client.patch(f"/api/control/people/{sara['id']}", json={"name": "SARA"}).json()["name"] == "SARA"
    assert [p["name"] for p in client.get("/api/control/people").json()] == ["Alex", "SARA"]
