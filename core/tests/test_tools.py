"""Pebbo's tools, their permissions, and the filter against claimed actions."""

import asyncio
from datetime import timedelta
from typing import Any

import numpy as np
import pytest

from pebbo import clock
from pebbo.store import Person, Store
from pebbo.tools import builtin_tools
from pebbo.tools.memory import memory_text
from pebbo.tools.registry import GUEST_UNCONFIRMED, GUEST_UNKNOWN, OWNER_ONLY, Tool, ToolContext, ToolResult
from pebbo.tools.reminders import reminder_task
from pebbo.voice.assistant import ActionAgent
from pebbo.voice.honesty import HonestSpeech, claims_action
from pebbo.voice.session import ConversationState


@pytest.fixture
def store() -> Store:
    return Store(":memory:")


class Runner:
    """Calls tools through the registry the way the action agent does."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.state = ConversationState(store, recognizer=None)
        self.registry = builtin_tools()

    def call(self, tool: str, **arguments: Any) -> ToolResult:
        context = ToolContext(self.store, self.state.person, self.state)
        return asyncio.run(self.registry.call(tool, arguments, context))

    def owner(self) -> Person:
        self.state.person = self.store.add_person("Alex", "owner")
        return self.state.person


def in_days(days: int, minutes: int = 0) -> str:
    """A local due time a few days from now at 08:00, as the action agent writes it."""
    moment = clock.now().replace(hour=8, minute=minutes, second=0, microsecond=0) + timedelta(days=days)
    return moment.strftime("%Y-%m-%dT%H:%M")


def test_guests_cannot_store_anything_and_hear_why(store: Store) -> None:
    runner = Runner(store)

    assert runner.call("remember", text="Mag Pizza", explicit=True).say == GUEST_UNKNOWN
    assert runner.call("remember", text="Mag Pizza", explicit=False).say == ""
    runner.state.claimed_names.add("Sara")
    assert runner.call("set_reminder", text="Training", due=in_days(1)).say == GUEST_UNCONFIRMED
    assert store.all_memories() == [] and store.reminders() == []


def test_owner_only_tools_are_refused_to_others(store: Store) -> None:
    runner = Runner(store)

    async def lock(_context: ToolContext, _arguments: dict[str, Any]) -> ToolResult:
        return ToolResult("Abgeschlossen.", outcome="done")

    runner.registry.register(Tool("lock_door", "Schliesst ab.", {"type": "object"}, lock, permission="owner"))
    runner.state.person = store.add_person("Alex", "owner")
    kid = store.add_person("Mia", "child")
    assert runner.call("lock_door").say == "Abgeschlossen."
    runner.state.person = kid
    assert runner.call("lock_door").say == OWNER_ONLY


def test_a_failing_tool_is_reported_not_raised(store: Store) -> None:
    runner = Runner(store)

    async def broken(_context: ToolContext, _arguments: dict[str, Any]) -> ToolResult:
        raise RuntimeError("kaputt")

    runner.registry.register(
        Tool("broken", "Geht kaputt.", {"type": "object"}, broken, permission="everyone")
    )
    result = runner.call("broken")
    assert not result.ok and result.say
    assert runner.call("does_not_exist").outcome == "unknown"


def test_remember_forget_and_duplicates(store: Store) -> None:
    runner = Runner(store)
    alex = runner.owner()

    assert runner.call("remember", text="Mag Kaffee ohne Zucker", explicit=True).say == (
        "Hab ich mir gemerkt: Mag Kaffee ohne Zucker."
    )
    assert (
        runner.call("remember", text="Die Person mag Kaffee ohne Zucker.", explicit=True).outcome == "known"
    )
    learned = runner.call("remember", text="Spielt Gitarre", explicit=False)
    assert learned.outcome == "stored" and learned.say == ""
    assert {m.text: m.source for m in store.memories(alex.id)} == {
        "Mag Kaffee ohne Zucker": "said",
        "Spielt Gitarre": "learned",
    }
    assert runner.call("forget", what="zuletzt").say == "Okay, vergessen: Spielt Gitarre."
    assert runner.call("forget", what="Kaffee").outcome == "deleted"
    assert runner.call("forget", what="Tennis").say == "Dazu hatte ich nichts gespeichert."


def test_reminders_are_validated_deduplicated_and_cancelled(store: Store) -> None:
    runner = Runner(store)
    runner.owner()

    assert runner.call("set_reminder", text="Paket", due="2000-01-01T08:00").outcome == "invalid"
    planned = runner.call("set_reminder", text="Erinnere mich ans Paket mitnehmen", due=in_days(2))
    assert planned.outcome == "planned" and planned.say.endswith(": Paket mitnehmen.")
    assert runner.call("set_reminder", text="Paket mitnehmen", due=in_days(2, 1)).outcome == "known"
    assert runner.call("set_reminder", text="Paket mitnehmen", due=in_days(3)).outcome == "planned"
    assert len(store.reminders()) == 2
    assert runner.call("cancel_reminder", what="Paket").outcome == "deleted"
    assert runner.call("cancel_reminder", what="Zahnarzt").outcome == "deleted"
    assert runner.call("cancel_reminder", what="Zahnarzt").outcome == "missing"


def test_introductions_claim_the_voice_after_enough_speech(store: Store) -> None:
    store.add_person("Alexander", "owner")
    runner = Runner(store)

    waiting = runner.call("introduce", name="alexandar")
    assert waiting.outcome == "waiting" and "noch einen Satz" in waiting.say
    assert store.voice_claims() == [] and runner.state.pending_name == "Alexander"

    runner.state.unknown_embedding = np.ones(8, dtype=np.float32)
    pending = ActionAgent(runner.state)._claim_pending_name(ToolContext(store, None, runner.state))
    assert pending is not None and "Kontrollzentrum" in pending.say
    assert [c.claimed_name for c in store.voice_claims()] == ["Alexander"]
    assert runner.call("introduce", name="Alexander").outcome == "pending"


def test_introductions_from_known_voices_or_of_pebbo_are_ignored(store: Store) -> None:
    runner = Runner(store)
    runner.state.unknown_embedding = np.ones(8, dtype=np.float32)

    assert runner.call("introduce", name="Pebbo").outcome == "ignored"
    stranger = runner.call("introduce", name="tom")
    assert stranger.outcome == "claimed" and "noch nicht" in stranger.say
    runner.owner()
    assert runner.call("introduce", name="Sara").outcome == "ignored"


def test_misheard_names_find_the_household_member(store: Store) -> None:
    alex = store.add_person("Alexander", "owner")

    assert store.find_similar_person("alexander") == alex
    assert store.find_similar_person("Alexandar") == alex
    assert store.find_similar_person("Sara") is None
    assert store.find_similar_person("Al") is None


def test_texts_are_stored_cleanly() -> None:
    assert memory_text("Die Person mag Tee.") == "Mag Tee"
    assert memory_text("mag Kaffee ohne Zucker") == "Mag Kaffee ohne Zucker"
    assert memory_text("Spielt Fußball") == "Spielt Fussball"
    assert reminder_task("Erinnere mich ans Training") == "Training"
    assert reminder_task("Denk dran: Tee in der Küche!") == "Tee in der Küche"
    assert reminder_task("Erinnere Alex an den Tee") == "Den Tee"
    assert reminder_task("Bitte erinnere mich ans Training") == "Training"


def test_claimed_actions_are_not_spoken_but_system_sentences_are() -> None:
    for claim in [
        "Ich hab's mir gemerkt.",
        "Gemerkt!",
        "Das merke ich mir.",
        "Ist notiert.",
        "Ich erinnere dich morgen um sieben.",
        "Die Erinnerung ist gesetzt.",
        "Hab ich gelöscht.",
        "Alles gemerkt!",
        "Kaffee mit Milch, ich notier's mir.",
    ]:
        assert claims_action(claim), claim
    for fine in [
        "Erinnerst du dich an letzten Sommer?",
        "Kaffee mit Milch klingt gut.",
        "Vergiss nicht, Wasser zu trinken.",
        "Gern!",
    ]:
        assert not claims_action(fine), fine

    speech = HonestSpeech()
    assert speech.filter("Ich merke mir das.") == ""
    speech.allow("Hab ich mir gemerkt: Mag Tee. Ich erinnere dich morgen um 07:30: Training.")
    assert speech.filter("Hab ich mir gemerkt: Mag Tee.") == "Hab ich mir gemerkt: Mag Tee."
    assert speech.filter("Ich erinnere dich morgen um 07:30: Training.") != ""


def test_a_changed_fact_replaces_the_old_one(store: Store) -> None:
    runner = Runner(store)
    alex = runner.owner()
    store.add_memory(alex.id, "fact", "Trinkt Kaffee mit Zucker")
    store.add_memory(alex.id, "fact", "Spielt Gitarre")

    result = runner.call(
        "remember", text="Trinkt Kaffee ohne Zucker", explicit=True, replaces="Trinkt Kaffee mit Zucker"
    )

    assert result.say == "Alles klar, geändert: Trinkt Kaffee ohne Zucker."
    assert sorted(m.text for m in store.memories(alex.id)) == ["Spielt Gitarre", "Trinkt Kaffee ohne Zucker"]
    unrelated = runner.call("remember", text="Mag Tee", explicit=True, replaces="Spielt Gitarre")
    assert unrelated.say == "Hab ich mir gemerkt: Mag Tee." and len(store.memories(alex.id)) == 3


def test_a_variant_of_a_stored_fact_updates_it(store: Store) -> None:
    runner = Runner(store)
    alex = runner.owner()
    store.add_memory(alex.id, "fact", "Trinkt Kaffee mit Milch und Zucker")
    store.add_memory(alex.id, "fact", "Mag Tee")

    assert runner.call("remember", text="Trinkt Kaffee mit Milch, aber ohne Zucker", explicit=True).say == (
        "Alles klar, geändert: Trinkt Kaffee mit Milch, aber ohne Zucker."
    )
    assert runner.call("remember", text="Mag Kaffee", explicit=True).say == "Hab ich mir gemerkt: Mag Kaffee."
    assert sorted(m.text for m in store.memories(alex.id)) == [
        "Mag Kaffee",
        "Mag Tee",
        "Trinkt Kaffee mit Milch, aber ohne Zucker",
    ]


def test_reminders_in_a_number_of_minutes(store: Store) -> None:
    runner = Runner(store)
    runner.owner()

    planned = runner.call("set_reminder", text="Tee", in_minutes=2)
    assert planned.outcome == "planned"
    due = store.reminders()[0].due_at - clock.now().timestamp()
    assert 100 < due < 125
    assert runner.call("set_reminder", text="Tee", in_minutes="viel").outcome == "invalid"
    assert runner.call("set_reminder", text="Tee", in_minutes=-5).outcome == "invalid"
