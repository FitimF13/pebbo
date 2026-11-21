"""Storage, voice matching, time handling and the reminder scheduler."""

import asyncio
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from pebbo import clock
from pebbo.people.speaker import MATCH_THRESHOLD, Identification, best_match, merged, normalise
from pebbo.reminders import ReminderScheduler, reminder_text
from pebbo.store import Store
from pebbo.voice.session import ConversationState

ZURICH = ZoneInfo("Europe/Zurich")


@pytest.fixture
def store() -> Store:
    return Store(":memory:")


def test_people_need_one_owner_and_valid_roles(store: Store) -> None:
    owner = store.add_person("Alex", "owner")
    store.add_person("Sara", "adult")

    with pytest.raises(ValueError, match="owner"):
        store.add_person("Kim", "owner")
    with pytest.raises(ValueError, match="role"):
        store.add_person("Kim", "boss")  # type: ignore[arg-type]
    assert [p.name for p in store.people()] == ["Alex", "Sara"]
    assert store.find_person("sara") is not None
    assert owner.role == "owner"


def test_memories_are_separated_per_person_and_cascade(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    sara = store.add_person("Sara", "adult")
    store.add_memory(alex.id, "fact", "Mag Kaffee ohne Zucker")
    store.add_memory(sara.id, "fact", "Spielt Tennis")
    store.add_memory(None, "fact", "Der Ersatzschlüssel liegt in der Schublade")

    assert [m.text for m in store.memories(alex.id)] == ["Mag Kaffee ohne Zucker"]
    assert [m.text for m in store.memories(None)] == ["Der Ersatzschlüssel liegt in der Schublade"]
    store.remove_person(sara.id)
    assert all(m.person_id != sara.id for m in store.all_memories())


def test_old_summaries_are_pruned(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    for index in range(25):
        store.add_memory(alex.id, "summary", f"Gespräch {index}")

    store.prune_summaries(alex.id, keep=20)

    assert len(store.memories(alex.id, kind="summary")) == 20


def test_reminders_become_due_and_can_be_cancelled(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    soon = store.add_reminder(alex.id, "Paket mitnehmen", time.time() - 1)
    later = store.add_reminder(alex.id, "Training", time.time() + 3600)

    assert [r.id for r in store.due_reminders(time.time())] == [soon.id]
    assert store.cancel_reminder(later.id)
    assert not store.cancel_reminder(later.id)
    store.mark_delivered(soon.id)
    assert store.reminders(alex.id) == []


def test_voice_matching_uses_thresholds() -> None:
    rng = np.random.default_rng(1)
    alex, sara = normalise(rng.normal(size=192)), normalise(rng.normal(size=192))
    prints = {1: (alex, 5), 2: (sara, 5)}

    assert best_match(normalise(alex + 0.2 * rng.normal(size=192) / 14), prints)[0] == 1
    assert best_match(normalise(rng.normal(size=192)), prints)[0] is None
    assert MATCH_THRESHOLD > 0.43


def test_merged_fingerprint_stays_normalised() -> None:
    vector, samples = merged(None, 0, np.array([3.0, 4.0]))
    vector, samples = merged(vector, samples, np.array([0.0, 1.0]))

    assert samples == 2
    assert abs(float(np.linalg.norm(vector)) - 1.0) < 1e-6


def test_voice_claims_link_known_names(store: Store) -> None:
    sara = store.add_person("Sara", "adult")
    claim = store.add_voice_claim("sara", np.ones(4, dtype=np.float32))
    stranger = store.add_voice_claim("Kim", np.ones(4, dtype=np.float32))

    assert claim.person_id == sara.id
    assert stranger.person_id is None
    taken = store.take_voice_claim(claim.id)
    assert taken is not None and taken[1].shape == (4,)
    assert [c.id for c in store.voice_claims()] == [stranger.id]


def test_conversation_state_switches_to_guest_and_back(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    state = ConversationState(store, recognizer=None)
    embedding = normalise(np.ones(8, dtype=np.float32))

    state.apply(Identification(None, 0.2, embedding))
    assert state.is_guest and state.unknown_samples == 1
    state.apply(Identification(alex.id, 0.6, embedding))
    assert state.person == store.person(alex.id) and state.unknown_embedding is None
    state.reset()
    assert state.is_guest and not state.people_in_conversation


def test_a_clearly_different_voice_becomes_a_guest_even_in_a_short_turn(store: Store) -> None:
    sara = store.add_person("Sara", "owner")
    state = ConversationState(store, recognizer=None)
    embedding = normalise(np.ones(8, dtype=np.float32))
    state.apply(Identification(sara.id, 0.7, embedding), seconds=3.5)

    # An uncertain short turn keeps Sara, so she does not lose her context mid-sentence.
    state.apply(Identification(None, 0.5, embedding), seconds=2.0)
    assert state.person is not None and state.person.id == sara.id
    # A short turn that clearly sounds like someone else is a guest (measured: 0.18 to 0.28).
    state.apply(Identification(None, 0.23, embedding), seconds=2.7)
    assert state.is_guest


def test_the_conversation_history_belongs_to_the_recognised_person(store: Store) -> None:
    sara = store.add_person("Sara", "owner")
    state = ConversationState(store, recognizer=None)
    state.people_in_conversation.add(sara.id)
    assert state.history_person() is None  # Only guests spoke so far.
    state.history_owner = sara.id
    assert state.history_person() == sara
    state.reset()
    assert state.history_owner is None


def test_spoken_datetimes() -> None:
    reference = datetime(2026, 11, 19, 17, 0, tzinfo=ZURICH)

    assert clock.spoken_datetime(datetime(2026, 11, 19, 19, 0, tzinfo=ZURICH), reference) == "heute um 19:00"
    assert clock.spoken_datetime(datetime(2026, 11, 20, 7, 30, tzinfo=ZURICH), reference) == "morgen um 07:30"
    assert clock.spoken_datetime(datetime(2026, 11, 24, 8, 0, tzinfo=ZURICH), reference) == (
        "Dienstag, 24. November um 08:00"
    )
    assert "Donnerstag, 19. November 2026, 17:00" in clock.describe_now(reference)


def test_due_times_must_be_plausible() -> None:
    reference = datetime(2026, 11, 19, 17, 0, tzinfo=ZURICH)

    assert clock.parse_due("2026-11-20T07:30", reference).hour == 7
    with pytest.raises(ValueError, match="Vergangenheit"):
        clock.parse_due("2026-11-19T08:00", reference)
    with pytest.raises(ValueError, match="Jahr"):
        clock.parse_due("2028-01-01T08:00", reference)
    with pytest.raises(ValueError, match="Format"):
        clock.parse_due("morgen früh", reference)


def test_reminder_wording_mentions_late_delivery(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    reminder = store.add_reminder(alex.id, "Paket mitnehmen", time.time() - 600)

    assert (
        reminder_text(reminder, alex, reminder.due_at + 5) == "Alex, ich soll dich erinnern: Paket mitnehmen."
    )
    assert "du hattest eine Erinnerung" in reminder_text(reminder, alex, reminder.due_at + 600)


def test_scheduler_speaks_due_reminders_only_when_someone_listens(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    store.add_reminder(alex.id, "Paket mitnehmen", time.time() - 1)
    scheduler = ReminderScheduler(store)
    spoken: list[str] = []

    async def speak(text: str) -> None:
        spoken.append(text)

    assert asyncio.run(scheduler.deliver_due()) == 0
    scheduler.connect(speak)
    assert asyncio.run(scheduler.deliver_due()) == 1
    assert spoken == ["Alex, ich soll dich erinnern: Paket mitnehmen."]
    assert asyncio.run(scheduler.deliver_due()) == 0


class LearningRecorder:
    """Stands in for the speaker recognizer and records what it learns."""

    def __init__(self) -> None:
        self.learned: list[int] = []

    def learn(self, person_id: int, _embedding: np.ndarray) -> None:
        self.learned.append(person_id)


def test_young_voiceprints_learn_from_every_matching_turn(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    recorder = LearningRecorder()
    state = ConversationState(store, recognizer=recorder)  # type: ignore[arg-type]
    embedding = normalise(np.ones(8, dtype=np.float32))

    store.save_voiceprint(alex.id, embedding, 1)
    state.apply(Identification(alex.id, 0.6, embedding))
    assert recorder.learned == [alex.id]

    store.save_voiceprint(alex.id, embedding, 20)
    state.apply(Identification(alex.id, 0.6, embedding))
    assert recorder.learned == [alex.id]
