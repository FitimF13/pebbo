"""Text chat with Pebbo from the phone app.

The chat uses the same persona, per-person context and action agent as the voice
conversation (see ``pebbo.voice.assistant``): the action agent picks tools from the
registry while the language model answers, the registry checks the permissions, and the
tools' sentences are returned after the answer. Each phone keeps a short history of its
own, so "vergiss das" still knows what "das" is.
"""

from __future__ import annotations

import asyncio
import json
import re
import urllib.request
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from loguru import logger
from pipecat.processors.aggregators.llm_context import LLMContext

from pebbo.config import VoiceConfig
from pebbo.netguard import is_local_address
from pebbo.store import Person, Store
from pebbo.tools.registry import ToolRegistry
from pebbo.voice.assistant import (
    TRANSCRIPT_LEVEL,
    ActionAgent,
    confirmation_sentences,
    context_message,
    refresh,
)
from pebbo.voice.emotion import EMOTIONS, split_emotion
from pebbo.voice.honesty import HonestSpeech
from pebbo.voice.session import ConversationState

if TYPE_CHECKING:
    from pebbo.voice.pipeline import VoiceServices

# Messages of a phone's chat the model sees: the last five exchanges.
HISTORY_MESSAGES = 10
MAX_ANSWER_TOKENS = 200
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
EMPTY_ANSWER = "Hm, dazu fällt mir gerade nichts ein."


@dataclass(frozen=True)
class ChatModel:
    """Where the chat thinks: the Ollama endpoint, the answer model and the action agent's model."""

    base_url: str
    model: str
    decision_model: str


def current_model(voice: VoiceServices | None) -> Callable[[], ChatModel]:
    """The model of the best reachable compute device, as for a new voice conversation."""
    config = voice.config if voice is not None else VoiceConfig()

    def current() -> ChatModel:
        if voice is None:
            return ChatModel(config.llm_base_url, config.llm_model, config.decision_model or config.llm_model)
        device = voice.device()
        decision = config.decision_model if device.id == 0 else ""
        return ChatModel(device.base_url, device.model, decision or device.model)

    return current


class ChatUnavailable(Exception):
    """The language model could not be reached."""


@dataclass(frozen=True)
class ChatReply:
    answer: str
    emotion: str
    # What Pebbo did, as the tools' short sentences.
    actions: list[str]


def complete(base_url: str, model: str, messages: list[dict[str, Any]]) -> str:
    """Ask the model for Pebbo's answer, on this computer or a compute device at home.

    Like the model router, only addresses that are not on the public internet are allowed.
    """
    parts = urlsplit(base_url)
    host = parts.hostname or ""
    if parts.scheme not in ("http", "https") or not (host == "localhost" or is_local_address(host)):
        raise ValueError("Pebbo only talks to a model on this computer or in the home network.")
    body = {"model": model, "stream": False, "max_tokens": MAX_ANSWER_TOKENS, "messages": messages}
    request = urllib.request.Request(  # noqa: S310 - the scheme and host are checked above
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        reply = json.loads(response.read())
    return str(reply.get("choices", [{}])[0].get("message", {}).get("content") or "")


def honest_answer(text: str, allowed: list[str]) -> str:
    """Drop sentences that claim an action the system did not carry out (see pebbo.voice.honesty)."""
    speech = HonestSpeech()
    for sentence in allowed:
        speech.allow(sentence)
    kept = [speech.filter(sentence) for sentence in _SENTENCE_END.split(text.strip())]
    return " ".join(sentence for sentence in kept if sentence).strip()


@dataclass
class _Session:
    state: ConversationState
    history: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=HISTORY_MESSAGES))
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class TextChat:
    """Pebbo's text answers for paired phones, one short conversation per phone."""

    def __init__(
        self, store: Store, model: Callable[[], ChatModel], registry: ToolRegistry | None = None
    ) -> None:
        self._store = store
        self._model = model
        self._registry = registry
        self._sessions: dict[int, _Session] = {}

    def forget(self, phone_id: int) -> None:
        """Drop a phone's conversation, for example when it is unpaired."""
        self._sessions.pop(phone_id, None)

    def history(self, phone_id: int) -> list[dict[str, Any]]:
        session = self._sessions.get(phone_id)
        return list(session.history) if session else []

    async def reply(self, phone_id: int, person: Person, text: str) -> ChatReply:
        session = self._sessions.get(phone_id)
        if session is None:
            session = _Session(ConversationState(self._store, recognizer=None))
            self._sessions[phone_id] = session
        async with session.lock:
            state = session.state
            state.person = person
            state.people_in_conversation.add(person.id)
            logger.log(TRANSCRIPT_LEVEL, "App message: {}", text)
            messages = [*session.history, {"role": "user", "content": text}]
            model = self._model()
            agent = ActionAgent(state, model.base_url, model.decision_model, self._registry)
            initial: list[Any] = [dict(message) for message in messages]
            context = LLMContext(messages=initial)
            extra = await agent.source_context()
            refresh(context, context_message(state, extra=extra, channel="app"))
            prompt = [dict(message) for message in context.get_messages() if isinstance(message, dict)]
            # Deciding and answering run at the same time, as in the voice conversation.
            results, answer = await asyncio.gather(
                agent.act(person, messages),
                asyncio.to_thread(complete, model.base_url, model.model, prompt),
                return_exceptions=True,
            )
            if isinstance(answer, BaseException):
                logger.opt(exception=answer).warning("The language model did not answer the app")
                raise ChatUnavailable from answer
            if isinstance(results, BaseException):
                logger.opt(exception=results).warning("The action agent failed for the app")
                results = []
            actions = confirmation_sentences(results)
            emotion, rest = split_emotion(answer)
            answer_text = honest_answer(rest, actions)
            if not answer_text and not actions:
                answer_text = EMPTY_ANSWER
            session.history.append({"role": "user", "content": text})
            said = " ".join([answer_text, *actions]).strip()
            session.history.append({"role": "assistant", "content": said})
            return ChatReply(answer_text, emotion if emotion in EMOTIONS else "neutral", actions)
