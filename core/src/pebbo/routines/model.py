"""What a routine is made of, how it is read from the action agent and how Pebbo says it.

A routine has one trigger, any number of conditions and one or more actions, stored as small
JSON objects in Pebbo's own format:

- Triggers: ``time`` (``at`` HH:MM, optional ``weekdays``), ``sunrise`` and ``sunset``
  (optional ``offset_minutes`` and ``weekdays``), ``arrive`` and ``leave`` (``who`` is a
  person id, ``"anyone"``, ``"first"`` or ``"last"``), ``device`` (``entity``, optional ``to``).
- Conditions: ``weekday`` (``days``), ``time_window`` (``from``, ``to``), ``quiet_hours``,
  ``outside_quiet_hours``, ``person_home`` and ``person_away`` (``who``), ``nobody_home``,
  ``someone_home``, ``device_state`` (``entity``, ``state``).
- Actions: ``say`` (``text``), ``remind`` (``text``, optional ``in_minutes``), ``tool``
  (``tool``, ``arguments``) for any tool in the registry, so smart home tools work too.

The action agent fills these in from a sentence. :func:`normalise` accepts the loose shapes
small models produce and turns them into the stored format, or explains in German what is
missing. :func:`describe` reads a routine back in natural German.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from typing import Any

from pebbo import clock
from pebbo.store import Person, Store

TRIGGER_TYPES = ("time", "sunrise", "sunset", "arrive", "leave", "device")
CONDITION_TYPES = (
    "weekday",
    "time_window",
    "quiet_hours",
    "outside_quiet_hours",
    "person_home",
    "person_away",
    "nobody_home",
    "someone_home",
    "device_state",
)
ACTION_TYPES = ("say", "remind", "tool")
# Tools a routine may not call: teaching routines from routines would loop.
ROUTINE_TOOLS = (
    "teach_routine",
    "confirm_routine",
    "discard_routine",
    "list_routines",
    "pause_routine",
    "test_routine",
)
DEFAULT_COOLDOWN_MINUTES = 15
DEFAULT_DAILY_LIMIT = 6
MAX_ACTIONS = 10

_SHORT_DAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
_DAY_PREFIXES = {
    "mo": 0, "di": 1, "mi": 2, "do": 3, "fr": 4, "sa": 5, "so": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}  # fmt: skip
_WORKDAYS = ("werktag", "wochentag", "weekday", "workday", "arbeitstag", "mo-fr", "montag bis freitag")
_WEEKEND = ("wochenende", "weekend", "sa-so")
_EVERY_DAY = ("täglich", "taeglich", "jeden tag", "daily", "alle tage", "immer")
_SELF = {"", "ich", "mich", "mir", "me", "self", "selbst", "du", "dich"}
_ANYONE = {"jemand", "irgendwer", "irgendjemand", "anyone", "someone", "egal", "wer auch immer", "alle"}
_LAST = {"letzte", "der letzte", "die letzte", "letzter", "last", "niemand mehr", "zuletzt"}
_FIRST = {"erste", "der erste", "die erste", "erster", "first"}


class RoutineError(ValueError):
    """A routine that cannot be saved. The message is German and spoken to the person."""


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(item) for item in value).strip()
    return str(value).strip()


def _clock_text(value: Any) -> str:
    hour, minute = clock.parse_clock_time(_text(value))
    return f"{hour:02d}:{minute:02d}"


def parse_weekdays(value: Any) -> list[int]:
    """Weekdays as numbers (Monday is 0) from names, abbreviations, numbers or "werktags".

    An empty result means every day.
    """
    if value in (None, "", []):
        return []
    items = value if isinstance(value, list) else re.split(r"[,;/]|\bund\b", str(value))
    days: set[int] = set()
    numbers = [item for item in items if isinstance(item, int) and not isinstance(item, bool)]
    # Models write 0 to 6 or 1 to 7. A zero means the first.
    one_based = bool(numbers) and 0 not in numbers
    for item in items:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            day = item - 1 if one_based else item
            if 0 <= day <= 6:
                days.add(day)
            continue
        word = str(item).strip().lower().rstrip(".s")
        if not word:
            continue
        if any(word.startswith(every) for every in _EVERY_DAY):
            return []
        if any(word.startswith(workday) for workday in _WORKDAYS):
            days.update(range(5))
        elif any(word.startswith(weekend) for weekend in _WEEKEND):
            days.update((5, 6))
        elif word.isdigit():
            days.add(int(word) % 7)
        elif word[:3] in _DAY_PREFIXES:
            days.add(_DAY_PREFIXES[word[:3]])
        elif word[:2] in _DAY_PREFIXES:
            days.add(_DAY_PREFIXES[word[:2]])
        else:
            raise RoutineError(f"Den Wochentag «{item}» verstehe ich nicht.")
    return [] if len(days) == 7 else sorted(days)


def _who(value: Any, store: Store, person: Person, allowed: Sequence[str]) -> int | str:
    """A person reference: a person id, or "anyone", "first" or "last" where allowed."""
    word = _text(value).lower().strip(" .!")
    if isinstance(value, int) and not isinstance(value, bool) and store.person(value):
        return value
    if word in _SELF:
        return person.id
    for keyword, words in (("anyone", _ANYONE), ("last", _LAST), ("first", _FIRST)):
        if keyword in allowed and (word in words or word == keyword):
            return keyword
    found = store.find_similar_person(word)
    if found is None:
        raise RoutineError(f"Wen meinst du mit «{_text(value)}»? Diese Person kenne ich nicht.")
    return found.id


def sun_configured() -> bool:
    return bool(os.environ.get("PEBBO_LATITUDE") and os.environ.get("PEBBO_LONGITUDE"))


def normalise_trigger(raw: Any, store: Store, person: Person) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = {"type": raw}
    if not isinstance(raw, dict) or not raw.get("type"):
        raise RoutineError("Mir fehlt noch, wann die Routine starten soll.")
    kind = _text(raw.get("type")).lower()
    if kind not in TRIGGER_TYPES:
        raise RoutineError("Mir fehlt noch, wann die Routine starten soll.")
    if kind == "time":
        if not raw.get("at"):
            raise RoutineError("Um welche Uhrzeit soll das passieren?")
        try:
            at = _clock_text(raw["at"])
        except ValueError as error:
            raise RoutineError(str(error)) from error
        return {"type": "time", "at": at, "weekdays": parse_weekdays(raw.get("weekdays"))}
    if kind in ("sunrise", "sunset"):
        if not sun_configured():
            raise RoutineError(
                "Für Sonnenaufgang und Sonnenuntergang braucht Pebbo den Standort. Der Besitzer kann ihn in "
                "den Einstellungen mit PEBBO_LATITUDE und PEBBO_LONGITUDE eintragen."
            )
        offset = _int(raw.get("offset_minutes"), 0, -720, 720)
        return {"type": kind, "offset_minutes": offset, "weekdays": parse_weekdays(raw.get("weekdays"))}
    if kind in ("arrive", "leave"):
        allowed = ("anyone", "first") if kind == "arrive" else ("anyone", "last")
        return {"type": kind, "who": _who(raw.get("who"), store, person, allowed)}
    entity = _text(raw.get("entity"))
    if not entity:
        raise RoutineError("Welches Gerät meinst du?")
    trigger: dict[str, Any] = {"type": "device", "entity": entity}
    if _text(raw.get("to")):
        trigger["to"] = _text(raw.get("to"))
    return trigger


def normalise_condition(raw: Any, store: Store, person: Person) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = {"type": raw}
    kind = _text(raw.get("type") if isinstance(raw, dict) else "").lower()
    if not isinstance(raw, dict) or kind not in CONDITION_TYPES:
        raise RoutineError("Eine Bedingung habe ich nicht verstanden.")
    if kind == "weekday":
        days = parse_weekdays(raw.get("days") or raw.get("weekdays"))
        return {"type": kind, "days": days}
    if kind == "time_window":
        try:
            start, end = _clock_text(raw.get("from")), _clock_text(raw.get("to"))
        except ValueError as error:
            raise RoutineError("Von wann bis wann soll das gelten?") from error
        return {"type": kind, "from": start, "to": end}
    if kind in ("person_home", "person_away"):
        return {"type": kind, "who": _who(raw.get("who"), store, person, ())}
    if kind == "device_state":
        entity, state = _text(raw.get("entity")), _text(raw.get("state"))
        if not entity or not state:
            raise RoutineError("Welches Gerät in welchem Zustand meinst du?")
        return {"type": kind, "entity": entity, "state": state}
    return {"type": kind}


def normalise_action(raw: Any, tool_exists: Callable[[str], bool]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RoutineError("Was soll ich dann tun?")
    kind = _text(raw.get("type")).lower()
    if not kind and raw.get("tool"):
        kind = "tool"
    if kind == "say":
        text = _text(raw.get("text")) or _text(raw.get("spoken"))
        if not text:
            raise RoutineError("Was soll ich dann sagen?")
        return {"type": "say", "text": text}
    if kind == "remind":
        text = _text(raw.get("text")) or _text(raw.get("spoken"))
        if not text:
            raise RoutineError("Woran soll ich dich dann erinnern?")
        return {"type": "remind", "text": text, "in_minutes": _int(raw.get("in_minutes"), 0, 0, 24 * 60)}
    if kind == "tool":
        name = _text(raw.get("tool"))
        if name in ROUTINE_TOOLS or not tool_exists(name):
            raise RoutineError(f"Das kann ich in einer Routine noch nicht: {name or 'unbekannt'}.")
        arguments = raw.get("arguments")
        # Small models fill unused arguments with empty values, which tools may reject.
        given = {
            key: value
            for key, value in (arguments if isinstance(arguments, dict) else {}).items()
            if value not in (None, "", [], {})
        }
        action: dict[str, Any] = {"type": "tool", "tool": name, "arguments": given}
        spoken = _text(raw.get("spoken"))[:80]
        if spoken:
            action["spoken"] = spoken
        return action
    raise RoutineError("Was soll ich dann tun?")


def normalise(
    trigger: Any,
    conditions: Any,
    actions: Any,
    store: Store,
    person: Person,
    tool_exists: Callable[[str], bool],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Check and clean what the action agent sent. Raises :class:`RoutineError`."""
    clean_trigger = normalise_trigger(trigger, store, person)
    raw_conditions = conditions if isinstance(conditions, list) else [conditions] if conditions else []
    clean_conditions = [normalise_condition(c, store, person) for c in raw_conditions]
    raw_actions = actions if isinstance(actions, list) else [actions] if actions else []
    if not raw_actions:
        raise RoutineError("Was soll ich dann tun?")
    if len(raw_actions) > MAX_ACTIONS:
        raise RoutineError(f"Eine Routine kann höchstens {MAX_ACTIONS} Dinge tun.")
    clean_actions = [normalise_action(a, tool_exists) for a in raw_actions]
    return clean_trigger, clean_conditions, clean_actions


def _int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def limits(cooldown: Any, daily_limit: Any) -> tuple[int, int]:
    """Cooldown in minutes and runs per day, within sensible bounds."""
    return (
        _int(cooldown, DEFAULT_COOLDOWN_MINUTES, 0, 7 * 24 * 60),
        _int(daily_limit, DEFAULT_DAILY_LIMIT, 1, 100),
    )


def people_referenced(trigger: dict[str, Any], conditions: Sequence[dict[str, Any]]) -> set[int]:
    """The people a routine watches."""
    return {part["who"] for part in [trigger, *conditions] if isinstance(part.get("who"), int)}


# Reading a routine back -------------------------------------------------------


def _days_text(days: Sequence[int]) -> str:
    if not days:
        return ""
    if list(days) == [0, 1, 2, 3, 4]:
        return "Montag bis Freitag"
    if list(days) == [5, 6]:
        return "am Wochenende"
    names = [clock.WEEKDAYS[day] for day in days]
    return "am " + (names[0] if len(names) == 1 else ", ".join(names[:-1]) + " und " + names[-1])


def _join(parts: Sequence[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " und " + parts[-1]


class Names:
    def __init__(self, store: Store, person: Person | None) -> None:
        self._store, self._person = store, person

    def subject(self, who: Any) -> tuple[str, bool]:
        """A name, and whether it is the person Pebbo talks to (who is addressed as "du")."""
        if self._person is not None and who == self._person.id:
            return "du", True
        if who == "anyone":
            return "jemand", False
        if who == "first":
            return "die erste Person", False
        if who == "last":
            return "die letzte Person", False
        found = self._store.person(who) if isinstance(who, int) else None
        return (found.name if found else "jemand"), False


def describe_trigger(trigger: dict[str, Any], names: Names) -> tuple[str, bool]:
    """The trigger in German, and whether it is a "wenn" clause (otherwise a time phrase)."""
    kind = trigger["type"]
    if kind == "time":
        days = _days_text(trigger.get("weekdays", []))
        return (f"{days} um {trigger['at']}" if days else f"jeden Tag um {trigger['at']}"), False
    if kind in ("sunrise", "sunset"):
        event = "Sonnenaufgang" if kind == "sunrise" else "Sonnenuntergang"
        offset = int(trigger.get("offset_minutes", 0))
        when = (
            f"bei {event}"
            if offset == 0
            else f"{abs(offset)} Minuten {'nach' if offset > 0 else 'vor'} {event}"
        )
        days = _days_text(trigger.get("weekdays", []))
        return (f"{days} {when}" if days else f"jeden Tag {when}"), False
    if kind in ("arrive", "leave"):
        subject, addressed = names.subject(trigger["who"])
        if kind == "arrive":
            return f"wenn {subject} {'heimkommst' if addressed else 'heimkommt'}", True
        return f"wenn {subject} {'gehst' if addressed else 'geht'}", True
    target = f" auf «{trigger['to']}» wechselt" if trigger.get("to") else " sich ändert"
    return f"wenn {trigger['entity']}{target}", True


def describe_condition(condition: dict[str, Any], names: Names) -> str:
    kind = condition["type"]
    if kind == "weekday":
        days = condition.get("days", [])
        if days == [0, 1, 2, 3, 4]:
            return "es ein Werktag ist"
        if days == [5, 6]:
            return "Wochenende ist"
        return "es " + " oder ".join(clock.WEEKDAYS[d] for d in days) + " ist" if days else "es ein Tag ist"
    if kind == "time_window":
        return f"es zwischen {condition['from']} und {condition['to']} ist"
    if kind == "quiet_hours":
        return "gerade Ruhezeit ist"
    if kind == "outside_quiet_hours":
        return "gerade keine Ruhezeit ist"
    if kind in ("person_home", "person_away"):
        subject, addressed = names.subject(condition["who"])
        verb = "bist" if addressed else "ist"
        return f"{subject} {'da' if kind == 'person_home' else 'weg'} {verb}"
    if kind == "nobody_home":
        return "niemand mehr da ist"
    if kind == "someone_home":
        return "jemand da ist"
    return f"{condition['entity']} «{condition['state']}» ist"


def describe_action(action: dict[str, Any], first: bool) -> str:
    """An action as a verb phrase. The first one carries the subject "ich"."""
    kind = action["type"]
    if kind == "say":
        return f"sage ich «{action['text']}»" if first else f"sage «{action['text']}»"
    if kind == "remind":
        later = int(action.get("in_minutes", 0))
        when = f" {later} Minuten später" if later else ""
        return (
            f"erinnere ich dich{when} an «{action['text']}»"
            if first
            else f"erinnere dich{when} an «{action['text']}»"
        )
    spoken = str(action.get("spoken") or "").strip().rstrip(".")
    if spoken:
        return f"werde ich {spoken}" if first else f"werde {spoken}"
    arguments = ", ".join(f"{key}: {value}" for key, value in action.get("arguments", {}).items())
    detail = f" ({arguments})" if arguments else ""
    return f"nutze ich «{action['tool']}»{detail}" if first else f"nutze «{action['tool']}»{detail}"


def describe(
    trigger: dict[str, Any],
    conditions: Sequence[dict[str, Any]],
    actions: Sequence[dict[str, Any]],
    report: bool,
    store: Store,
    person: Person | None,
) -> str:
    """The routine as one or two German sentences, addressed to ``person``."""
    names = Names(store, person)
    when, clause = describe_trigger(trigger, names)
    checks = [describe_condition(c, names) for c in conditions]
    doing = [describe_action(a, i == 0) for i, a in enumerate(actions)]
    if clause:
        head = when + (" und " + " und ".join(checks) if checks else "") + ","
    else:
        head = when + (", wenn " + " und ".join(checks) + "," if checks else "")
    sentence = f"{head} {_join(doing)}."
    sentence = sentence[:1].upper() + sentence[1:]
    if report:
        sentence += " Danach sage ich, was ich getan habe."
    return sentence


def short_days() -> tuple[str, ...]:
    return _SHORT_DAYS
