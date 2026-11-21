"""Keep Pebbo from claiming actions it did not carry out.

The conversation model has no tools. Remembering, forgetting and reminders are decided and
carried out separately (see ``pebbo.voice.actions``), and the system confirms them with
fixed sentences. Small models still sometimes say "Ich hab's mir gemerkt" on their own,
also to guests for whom nothing is stored. Such sentences are not spoken. When the system did
carry out an action, the answer may confirm it. Sentences the system speaks itself, such as
due reminders, are registered here and always pass.
"""

from __future__ import annotations

import re
from collections import deque

_CLAIMS = [
    # "Ich hab's mir gemerkt", "Habe ich notiert", "hab das gelöscht"
    r"\b(?:hab|habe|hab's|habs|hab ich|habe ich)\b.{0,30}?"
    r"\b(?:gemerkt|notiert|gespeichert|abgespeichert|gelöscht|vergessen|eingetragen|eingeplant|vermerkt)\b",
    # "Ich merke mir das", "merk ich mir", "Das merke ich mir"
    r"\b(?:ich\s+merke?\s+(?:mir|es|das|dir)|merke?\s+ich\s+mir)\b",
    # "Alles gemerkt!", "ich notier's mir", "notiere ich"
    r"\balles\s+(?:klar,?\s+)?(?:gemerkt|notiert|gespeichert)\b",
    r"\bnotier(?:e|'|’)?s?\s+(?:ich\s+)?(?:mir|es|das)\b|\bnotiere\s+ich\b",
    # "Gemerkt!", "Notiert.", "Erledigt, gespeichert."
    r"^\W*(?:gemerkt|notiert|gespeichert|vermerkt|gelöscht|eingetragen)\b",
    # "Ist notiert", "ist gespeichert", "ist gelöscht"
    r"\b(?:ist|sind|wurde|wurden)\s+(?:jetzt\s+|nun\s+)?(?:gemerkt|notiert|gespeichert|gelöscht|vergessen|eingetragen)\b",
    # "Ich erinnere dich morgen um sieben", "erinnere ich dich"
    r"\b(?:ich\s+erinnere\s+dich|erinnere\s+ich\s+dich|ich\s+sag\s+dir\s+(?:dann\s+)?bescheid)\b",
    # "Die Erinnerung ist gesetzt", "Erinnerung gestellt"
    r"\berinnerung\b.{0,20}\b(?:gesetzt|gestellt|eingerichtet|erstellt|drin)\b",
]
_CLAIM = re.compile("|".join(_CLAIMS), re.IGNORECASE)
_SPACES = re.compile(r"\s+")


def claims_action(sentence: str) -> bool:
    """Whether a sentence claims that Pebbo remembered, forgot or planned something."""
    return bool(_CLAIM.search(sentence))


def _normal(text: str) -> str:
    return _SPACES.sub(" ", text).strip().lower()


class HonestSpeech:
    """A text transform for speech synthesis that drops sentences claiming actions.

    Sentences the system speaks itself are registered with :meth:`allow` and always pass.
    """

    def __init__(self, remembered: int = 20) -> None:
        self._allowed: deque[str] = deque(maxlen=remembered)
        self._claims_allowed = False

    def allow_claims(self, allowed: bool) -> None:
        """Whether the next answer may confirm actions, because the system really carried them out."""
        self._claims_allowed = allowed

    def allow(self, text: str) -> None:
        self._allowed.append(_normal(text))

    def is_allowed(self, sentence: str) -> bool:
        normal = _normal(sentence)
        return bool(normal) and any(normal in allowed for allowed in self._allowed)

    def filter(self, sentence: str) -> str:
        if claims_action(sentence) and not self._claims_allowed and not self.is_allowed(sentence):
            return ""
        return sentence

    async def transform(self, text: str, _text_type: object) -> str:
        """Pipecat text transform, applied to each sentence right before it is spoken."""
        return self.filter(text)
