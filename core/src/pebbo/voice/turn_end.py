"""End a user turn as soon as its transcript is in.

Pebbo's turn start strategies (the wake phrase and the backchannel filter) decide on
transcripts, so a turn starts only after the sentence was spoken and transcribed. Pipecat
then resets its stop strategy and, seeing a transcript without a speech pause in the new
turn, waits its STT safety window (0.8 s) before ending the turn. That cost every answer
0.8 s. When Smart Turn already found the finished sentence complete, the transcript that
starts the turn now ends it too. An unfinished sentence still gets the safety window, so a
short pause in the middle of a sentence does not cut it.
"""

from __future__ import annotations

from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy


class TranscriptTurnStopStrategy(TurnAnalyzerUserTurnStopStrategy):
    """Pipecat's Smart Turn stop strategy, for turns that start from a transcript."""

    async def handle_user_turn_started(self) -> None:
        finished = self._vad_stopped and not self._vad_user_speaking and self._turn_complete
        await super().handle_user_turn_started()
        if finished:
            # Keep the verdict about the speech that is already over, so its transcript ends the turn.
            self._vad_stopped = self._turn_complete = True
