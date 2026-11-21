"""Tools Pebbo can use, each with the permission it needs.

Pebbo has no list of command words. After each sentence the action agent (see
``pebbo.voice.actions``) reads the conversation and picks tools from this registry by their
name, description and parameters. Adding a capability means registering a tool, never
teaching new phrases. The registry, not the model, checks who may use a tool.

Every tool returns a :class:`ToolResult`. Its ``say`` is a short factual sentence spoken
after Pebbo's answer, so Pebbo never has to claim an action itself.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from loguru import logger

from pebbo.store import Person, Store

# everyone: also guests. household: recognised household members. owner: only the owner.
Permission = Literal["everyone", "household", "owner"]

GUEST_UNKNOWN = (
    "Dich kenne ich noch nicht. Sag mir zuerst, wie du heisst, dann merke ich mir Sachen für dich."
)
GUEST_UNCONFIRMED = (
    "Das mache ich gern, sobald deine Stimme im Kontrollzentrum bestätigt ist. "
    "Danach sag es mir einfach nochmal."
)
OWNER_ONLY = "Das darf bei mir nur der Besitzer."


@dataclass
class ToolContext:
    """Who a tool runs for, and the conversation it runs in."""

    store: Store
    person: Person | None
    # The conversation state (pebbo.voice.session.ConversationState), if any.
    state: Any = None


@dataclass
class ToolResult:
    """What a tool did. ``say`` is spoken to the person, an empty ``say`` stays quiet."""

    say: str = ""
    ok: bool = True
    # A short machine-readable outcome, for example "stored", "deleted" or "denied".
    outcome: str = ""
    data: dict[str, Any] = field(default_factory=dict)


ToolRun = Callable[[ToolContext, dict[str, Any]], Awaitable[ToolResult]]
# Returns lines for Pebbo's per-turn context, for example the state of the lights.
ContextRun = Callable[[ToolContext], Awaitable[str]]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: ToolRun
    permission: Permission = "household"
    # Where the tool comes from: "pebbo" or "mcp:<server>".
    source: str = "pebbo"

    def schema(self) -> dict[str, Any]:
        """The tool in the OpenAI function format that Ollama understands."""
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


def passive(arguments: dict[str, Any]) -> bool:
    """Whether the agent chose this action on its own rather than because the person asked."""
    return arguments.get("explicit") is False


@dataclass
class ContextSource:
    """Something a tool source adds to Pebbo's context before each answer, never for guests."""

    source: str
    run: ContextRun
    permission: Permission = "household"


class ToolRegistry:
    """The tools available to the action agent."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._contexts: dict[str, ContextSource] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def unregister_source(self, source: str) -> None:
        self._tools = {name: tool for name, tool in self._tools.items() if tool.source != source}
        self._contexts.pop(source, None)

    def add_context(self, context: ContextSource) -> None:
        self._contexts[context.source] = context

    async def context(self, context: ToolContext) -> list[str]:
        """What the context sources add for this person. Guests get nothing. Never raises."""
        person = context.person
        if person is None:
            return []
        texts = []
        for source in list(self._contexts.values()):
            if source.permission == "owner" and person.role != "owner":
                continue
            try:
                text = await source.run(context)
            except Exception:
                logger.exception("Context from {} failed", source.source)
                continue
            if text:
                texts.append(text)
        return texts

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def tools(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def denial(self, tool: Tool, context: ToolContext) -> ToolResult | None:
        """Why the person may not use the tool, or ``None`` if they may."""
        person = context.person
        if tool.permission == "everyone":
            return None
        if person is None:
            claimed = bool(getattr(context.state, "claimed_names", None))
            return ToolResult(GUEST_UNCONFIRMED if claimed else GUEST_UNKNOWN, ok=False, outcome="denied")
        if tool.permission == "owner" and person.role != "owner":
            return ToolResult(OWNER_ONLY, ok=False, outcome="denied")
        return None

    async def call(self, name: str, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        """Run a tool after checking the permission. Never raises."""
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(ok=False, outcome="unknown")
        denied = self.denial(tool, context)
        if denied is not None:
            # Something the agent chose on its own is not worth a refusal.
            return ToolResult(ok=False, outcome="denied") if passive(arguments) else denied
        try:
            return await tool.run(context, arguments)
        except Exception as error:
            logger.exception("Tool {} failed", name)
            return ToolResult(
                "Das hat leider nicht geklappt.", ok=False, outcome="failed", data={"error": str(error)}
            )


def speaker(context: ToolContext) -> Person:
    """The person a household tool runs for. The registry already refused guests."""
    if context.person is None:
        raise PermissionError("This tool needs a recognised person.")
    return context.person


def text_argument(arguments: dict[str, Any], key: str) -> str:
    """A text argument as a clean string. Models sometimes send numbers or lists."""
    value = arguments.get(key, "")
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(str(item) for item in value).strip()
    return json.dumps(value, ensure_ascii=False) if value not in (None, "") else ""
