"""Ask a local Ollama model typical questions with Pebbo's real persona and context, many times.

Measures how often the answers are right, what Pebbo would really say after its filters,
how long they are and how fast the first token comes. Use it to check a prompt change or to
compare models before switching. The people and facts are synthetic.

Usage:
    uv run python tools/persona_probe.py [--rounds 10] [--model pebbo-ministral] [--only who,coffee] [--show]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from pipecat.processors.aggregators.llm_context import LLMContext

from pebbo.netguard import is_local_address
from pebbo.store import Store
from pebbo.voice.assistant import context_message, refresh
from pebbo.voice.emotion import split_emotion
from pebbo.voice.honesty import HonestSpeech, claims_action
from pebbo.voice.session import ConversationState
from pebbo.voice.speech_text import clean_for_speech, strip_notes

MARKUP = re.compile(r"[*()\[\]_#]")
SENTENCE = re.compile(r"(?<=[.!?])\s+")
Judge = Callable[[str], bool]


def words(text: str) -> int:
    return len(text.split())


def plain(text: str) -> bool:
    return not MARKUP.search(text)


def knows_coffee(text: str) -> bool:
    low = text.lower()
    return "ohne zucker" in low and not re.search(r"\bich (trink|mag|nehm)|meinst\W+mich|ich bin nur", low)


def names_speaker(text: str) -> bool:
    low = text.lower()
    return "sara" in low and not re.search(r"\bich bin\b[^.!?]{0,12}\bsara", low)


def promises_nothing(text: str) -> bool:
    low = text.lower()
    passes_on = re.search(r"\b(sag|richte|bring|erzähl|geb|leit)\w*\b[^.!?]{0,25}\b(ich|'s)\b", low)
    promised = re.search(r"\bich (sag|richte|bring|merk|werd)", low)
    return "sara" not in low and not passes_on and not promised and not claims_action(text)


def tells_nothing_about_sara(text: str) -> bool:
    return not re.search(r"zucker|schwarz|milch", text.lower())


def invents_nobody(text: str) -> bool:
    return not re.search(
        r"haar|kaffee|zucker|lach|geschicht|reise|\bmag\b|liebt|arbeitet|wohnt", text.lower()
    )


def short(text: str) -> bool:
    return 0 < words(text) <= 25 and plain(text)


def story(text: str) -> bool:
    return 3 <= len(SENTENCE.split(text)) <= 8 and plain(text) and "roboter" in text.lower()


def only_agrees(text: str) -> bool:
    return 0 < words(text) <= 20 and plain(text) and "erinnerung" not in text.lower()


# Name, who speaks, what they say, and what counts as a right answer.
CASES: list[tuple[str, str, str, Judge]] = [
    ("coffee", "sara", "Hey Pebo, wie trinke ich eigentlich meinen Kaffee?", knows_coffee),
    ("coffee2", "sara", "Weisst du noch, wie ich meinen Kaffee trinke?", knows_coffee),
    ("who", "sara", "Hey Pebbo, weißt du wer ich bin?", names_speaker),
    ("guest_remember", "guest", "Merk dir bitte, dass ich gern Pfefferminztee trinke.", promises_nothing),
    ("guest_sara", "guest", "Pebbo, wie trinkt die Sarah ihren Kaffee?", tells_nothing_about_sara),
    ("guest_unknown", "guest", "Was weisst du über Azahara?", invents_nobody),
    # A misheard sentence from the end-to-end test that made Ministral invent a person.
    ("guest_misheard", "guest", "Ich erinnerung an Azahara gerade offen.", invents_nobody),
    ("reminder", "sara", "Hey Pebbo, erinnere mich in zwei Minuten an den Tee.", only_agrees),
    ("remember", "sara", "Merk dir, dass ich gern Pfefferminztee trinke.", only_agrees),
    ("smalltalk", "sara", "Hey Pebbo, wie geht's dir heute?", short),
    ("guest_talk", "guest", "Was würdest du mir heute zum Mittagessen empfehlen?", short),
    (
        "story",
        "sara",
        "Hey Pebbo, erzähl mir bitte eine Geschichte über einen kleinen Roboter, der Kuchen backen lernt.",
        story,
    ),
]


def ask(base_url: str, model: str, messages: list[Any]) -> tuple[str, float]:
    """The streamed answer and the seconds until its first token."""
    body = {"model": model, "stream": True, "max_tokens": 160, "messages": messages}
    request = urllib.request.Request(  # noqa: S310 - the host is checked in main()
        f"{base_url.rstrip('/')}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    started, first, parts = time.monotonic(), 0.0, []
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
        for line in response:
            line = line.strip()
            if not line.startswith(b"data:") or line.endswith(b"[DONE]"):
                continue
            delta = json.loads(line[5:])["choices"][0]["delta"].get("content") or ""
            if delta and not first:
                first = time.monotonic() - started
            parts.append(delta)
    return "".join(parts).replace("\n", " "), first


def spoken(answer: str) -> str:
    """What Pebbo would say: no emotion tag, no stage notes, cleaned, without claimed actions."""
    _emotion, rest = split_emotion(answer)
    honest = HonestSpeech()
    sentences = [honest.filter(clean_for_speech(s)) for s in SENTENCE.split(strip_notes(rest).strip())]
    return " ".join(s for s in sentences if s).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--model", default="pebbo-ministral")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--only", default="", help="comma-separated case names")
    parser.add_argument("--show", action="store_true", help="print every answer, not only wrong ones")
    args = parser.parse_args()
    host = urlsplit(args.base_url).hostname or ""
    if host != "localhost" and not is_local_address(host):
        raise SystemExit("The probe only talks to a model on this computer or in the home network.")

    store = Store(":memory:")
    sara = store.add_person("Sara", "owner")
    store.add_memory(sara.id, "fact", "Trinkt Kaffee ohne Zucker")
    only = set(filter(None, args.only.split(",")))
    ask(args.base_url, args.model, [{"role": "user", "content": "Hallo"}])  # load the model
    rows = []
    for name, speaker, text, judge in CASES:
        if only and name not in only:
            continue
        state = ConversationState(store, recognizer=None)
        state.person = sara if speaker == "sara" else None
        context = LLMContext()
        context.add_message({"role": "user", "content": text})
        refresh(context, context_message(state))
        raw_right = said_right = 0
        lengths: list[int] = []
        latencies: list[float] = []
        for _ in range(args.rounds):
            answer, first = ask(args.base_url, args.model, context.get_messages())
            said = spoken(answer)
            raw_right += judge(split_emotion(answer)[1].strip())
            said_right += judge(said)
            lengths.append(words(said))
            latencies.append(first)
            if args.show or not judge(said):
                print(f"{'ok ' if judge(said) else 'BAD'} {name:14} {answer!r} => {said!r}", flush=True)
        rows.append((name, raw_right, said_right, statistics.mean(lengths), statistics.median(latencies)))

    rounds = args.rounds
    print(f"\n{args.model}, {rounds} rounds. raw: the model's answer, spoken: after Pebbo's filters")
    print(f"{'case':16}{'raw':>7}{'spoken':>8}{'words':>7}{'first token':>13}")
    for name, raw_right, said_right, length, latency in rows:
        print(f"{name:16}{raw_right:>4}/{rounds}{said_right:>5}/{rounds}{length:>7.1f}{latency:>11.2f} s")


if __name__ == "__main__":
    main()
