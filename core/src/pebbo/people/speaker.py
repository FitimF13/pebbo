"""Recognise household members by their voice.

A speaker embedding model turns each utterance into a vector. Every person has one stored
fingerprint, the running mean of confident samples. Voice recognition identifies people for
personalisation only. It never authenticates sensitive actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from pebbo.store import Store

SAMPLE_RATE = 16_000
# Measured with CAM++ on real recordings: the same person scores at least 0.60, different
# people at most 0.43. Between the two thresholds Pebbo is unsure and treats the voice as a guest.
MATCH_THRESHOLD = 0.55
LEARN_THRESHOLD = 0.65
# Below this many samples a fingerprint also learns from turns above MATCH_THRESHOLD.
YOUNG_VOICEPRINT = 5
MIN_SECONDS = 1.0
MAX_SAMPLES = 200

MODEL_FILE = "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
MODEL_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/{MODEL_FILE}"


@dataclass(frozen=True)
class Identification:
    """Who spoke an utterance. ``person_id`` is ``None`` for an unknown or uncertain voice."""

    person_id: int | None
    score: float
    embedding: np.ndarray


def normalise(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector


def best_match(
    embedding: np.ndarray, voiceprints: dict[int, tuple[np.ndarray, int]]
) -> tuple[int | None, float]:
    """Return the closest person and the cosine similarity, or ``None`` below the threshold."""
    best_person, best_score = None, -1.0
    for person_id, (print_vector, _) in voiceprints.items():
        score = float(normalise(embedding) @ normalise(print_vector))
        if score > best_score:
            best_person, best_score = person_id, score
    if best_score < MATCH_THRESHOLD:
        return None, max(best_score, 0.0)
    return best_person, best_score


def merged(print_vector: np.ndarray | None, samples: int, embedding: np.ndarray) -> tuple[np.ndarray, int]:
    """Add one embedding to a running-mean fingerprint."""
    if print_vector is None or samples == 0:
        return normalise(embedding), 1
    weight = min(samples, MAX_SAMPLES - 1)
    return normalise(normalise(print_vector) * weight + normalise(embedding)), min(samples + 1, MAX_SAMPLES)


class SpeakerRecognizer:
    """Computes embeddings with a local ONNX model and matches them against stored voices."""

    def __init__(self, store: Store, model_path: Path) -> None:
        import sherpa_onnx

        self._store = store
        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(model_path), num_threads=2)
        self._extractor: Any = sherpa_onnx.SpeakerEmbeddingExtractor(config)

    def embed(self, samples: np.ndarray) -> np.ndarray:
        """Embed 16 kHz mono float samples."""
        stream = self._extractor.create_stream()
        stream.accept_waveform(SAMPLE_RATE, samples.astype(np.float32))
        stream.input_finished()
        return normalise(np.array(self._extractor.compute(stream), dtype=np.float32))

    def identify(self, samples: np.ndarray) -> Identification | None:
        """Identify the speaker of an utterance, or ``None`` if it is too short to tell."""
        if len(samples) < SAMPLE_RATE * MIN_SECONDS:
            return None
        embedding = self.embed(samples)
        person_id, score = best_match(embedding, self._store.voiceprints())
        return Identification(person_id, score, embedding)

    def learn(self, person_id: int, embedding: np.ndarray) -> None:
        """Strengthen a person's fingerprint with a confident sample."""
        current = self._store.voiceprints().get(person_id)
        vector, samples = merged(current[0] if current else None, current[1] if current else 0, embedding)
        self._store.save_voiceprint(person_id, vector, samples)
