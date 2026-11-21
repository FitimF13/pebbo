"""Unit tests for the voice logic that does not need speech models."""

import numpy as np
import pytest

from pebbo.voice.backchannel import SpokenTextMemory, Utterance, classify
from pebbo.voice.emotion import split_emotion
from pebbo.voice.pitch import StreamingSpeedup
from pebbo.voice.speech_text import clean_for_speech
from pebbo.voice.wake import addresses_pebbo, is_farewell, is_fragment, is_name, is_sleep_command


@pytest.mark.parametrize(
    "text",
    [
        "Hey Pebbo",
        "Hey Pebo, erzähl mir was",
        "Hallo Bebo!",
        "Pecco, wie geht es dir heute?",
        "hey peppo wie spät ist es",
    ],
)
def test_wakes_on_greeting_or_name_followed_by_words(text: str) -> None:
    assert addresses_pebbo(text)


@pytest.mark.parametrize(
    "text",
    [
        "Bebbo",
        "Pebbo?",
        "Wie spät ist es eigentlich?",
        "Tempo ist wichtig heute",
        "Peter kommt heute",
        "Ja genau",
    ],
)
def test_ignores_lone_names_and_other_sentences(text: str) -> None:
    assert not addresses_pebbo(text)


def test_name_matching_is_phonetic_but_not_too_loose() -> None:
    assert is_name("Pecco")
    assert is_name("pebble")
    assert not is_name("Pablo")
    assert not is_name("Tempo")


def test_short_transcripts_are_fragments() -> None:
    assert is_fragment("Hey, hey, bohr.")
    assert not is_fragment("Erzähl mir bitte eine Geschichte")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Mhm.", Utterance.BACKCHANNEL),
        ("Ja, genau.", Utterance.BACKCHANNEL),
        ("Okay cool", Utterance.BACKCHANNEL),
        ("Danke", Utterance.BACKCHANNEL),
        ("Halt, stopp bitte!", Utterance.STOP),
        ("Nein, morgen", Utterance.STOP),
        ("Warte mal kurz", Utterance.STOP),
        ("Erzähl mir lieber was über Katzen", Utterance.CONTENT),
    ],
)
def test_classifies_speech_while_pebbo_talks(text: str, expected: Utterance) -> None:
    assert classify(text) is expected


def test_recognises_its_own_voice_as_echo() -> None:
    memory = SpokenTextMemory()
    memory.add("Es war einmal ein kleiner Roboter, der fliegen lernen wollte.")

    assert classify("ein kleiner Roboter der fliegen", memory.recent_words()) is Utterance.ECHO
    assert classify("Erzähl lieber von Katzen", memory.recent_words()) is Utterance.CONTENT


def test_splits_known_emotion_tags() -> None:
    assert split_emotion("[happy] Hoi!") == ("happy", "Hoi!")
    assert split_emotion("  [ Proud ]Geschafft.") == ("proud", "Geschafft.")
    assert split_emotion("[excited] Wow") == (None, "Wow")
    assert split_emotion("Ohne Tag") == (None, "Ohne Tag")


@pytest.mark.parametrize(
    ("text", "spoken"),
    [
        ("Oh, das ist ja ein *perfekter* Anlass!", "Oh, das ist ja ein perfekter Anlass!"),
        ("Warum fragst du? *flattert mit den Flügeln*", "Warum fragst du?"),
        ("*kichert* Na klar!", "Na klar!"),
        ("Dann tanze ich. 😊", "Dann tanze ich."),
        ("Ich bin **super** – wirklich.", "Ich bin super, wirklich."),
        ("Hast du Angst? (lacht) Nein.", "Hast du Angst? Nein."),
    ],
)
def test_cleans_text_before_speaking(text: str, spoken: str) -> None:
    assert clean_for_speech(text) == spoken


@pytest.mark.parametrize("text", ["Okay, bye bye!", "Tschüss Pebbo", "Gute Nacht", "Bis später!", "Ciao"])
def test_recognises_farewells(text: str) -> None:
    assert is_farewell(text)


@pytest.mark.parametrize("text", ["Stopp.", "Halt, stopp bitte!", "Ruhe jetzt", "Pebbo, schlafen"])
def test_recognises_short_sleep_commands(text: str) -> None:
    assert is_sleep_command(text)


@pytest.mark.parametrize(
    "text", ["Nein, warte", "Erzähl mir mehr über das Stopp-Schild und seine Farbe", "Danke"]
)
def test_ignores_other_sentences_as_sleep_commands(text: str) -> None:
    assert not is_sleep_command(text)


def test_ignore_tag_is_recognised() -> None:
    assert split_emotion("[ignore]") == ("ignore", "")


def test_streaming_speedup_raises_pitch_without_clicks() -> None:
    samples = (np.sin(np.arange(24_000) / 24_000 * 2 * np.pi * 200) * 10_000).astype(np.int16)
    speedup = StreamingSpeedup(1.1)
    output = np.concatenate([speedup.process(chunk) for chunk in np.array_split(samples, 37)])

    assert abs(len(samples) / len(output) - 1.1) < 0.01
    assert np.abs(np.diff(output.astype(int))).max() < 1.2 * np.abs(np.diff(samples.astype(int))).max()


def test_removes_emotion_tags_in_the_middle_of_a_reply() -> None:
    assert (
        clean_for_speech("Und abends lache ich. [neutral] Mir geht's gut!")
        == "Und abends lache ich. Mir geht's gut!"
    )


def test_a_greeting_run_together_with_the_name_wakes_pebbo() -> None:
    assert addresses_pebbo("Eipepo, merk dir bitte, dass ich Tee mag.")
    assert addresses_pebbo("Heipebbo")
    assert addresses_pebbo("Pei Pei Bo Bitte, dass ich meinen Kaffee mit Milch trinke.")
    assert addresses_pebbo("Hey Pe Bo")
    assert addresses_pebbo("Hey people")  # how Whisper hears it through a body's Opus audio
    assert not addresses_pebbo("Die Bo ist da")
    assert not addresses_pebbo("Eis essen wir morgen")
    assert not addresses_pebbo("Heimat ist schön")
