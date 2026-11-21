"""Tools Pebbo uses to act, with the permissions they need."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pebbo.tools.memory import register_memory_tools
from pebbo.tools.registry import ToolRegistry
from pebbo.tools.reminders import register_reminder_tools

if TYPE_CHECKING:
    from pebbo.routines.structure import Structurer


def builtin_tools(structure: Structurer | None = None) -> ToolRegistry:
    """A registry with Pebbo's own tools. Integrations add theirs to it.

    ``structure`` lets ``teach_routine`` take plain words (see ``pebbo.routines.structure``).
    """
    # Imported here: routines and calendars use the registry module themselves.
    from pebbo.briefing import register_briefing_tools
    from pebbo.calendars.tools import register_calendar_tools
    from pebbo.routines.tools import register_routine_tools

    registry = ToolRegistry()
    register_memory_tools(registry)
    register_reminder_tools(registry)
    register_calendar_tools(registry)
    register_briefing_tools(registry)
    register_routine_tools(registry, structure)
    return registry
