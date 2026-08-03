"""Phrase-level vocal riding proposals that never modify audio or REAPER."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Literal


SourceKind = Literal["suno_stems", "organic_multitrack", "unknown"]

_PROFILE = {
    "suno_stems": {"limit_db": 1.0, "strength": 0.35},
    "organic_multitrack": {"limit_db": 3.0, "strength": 0.60},
    "unknown": {"limit_db": 1.5, "strength": 0.40},
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _phrase_regions(
    block_db: Any, block_seconds: float, activity_threshold_dbfs: float
) -> list[tuple[int, int]]:
    import numpy as np

    active_indexes = np.flatnonzero(block_db >= activity_threshold_dbfs)
    if active_indexes.size == 0:
        return []
    maximum_gap_blocks = max(1, round(0.20 / block_seconds))
    minimum_phrase_blocks = max(1, round(0.25 / block_seconds))
    regions: list[tuple[int, int]] = []
    first = previous = int(active_indexes[0])
    for raw_index in active_indexes[1:]:
        index = int(raw_index)
        if index - previous > maximum_gap_blocks + 1:
            if previous - first + 1 >= minimum_phrase_blocks:
                regions.append((first, previous + 1))
            first = index
        previous = index
    if previous - first + 1 >= minimum_phrase_blocks:
        regions.append((first, previous + 1))
    return regions


def build_vocal_rider_proposal(
    path: Path, source_kind: SourceKind
) -> dict[str, Any]:
    """Analyze a vocal WAV and return conservative source-time envelope points."""

    import numpy as np
    import soundfile as sf

    if source_kind not in _PROFILE:
        raise ValueError("unsupported source kind")
    path = Path(path).resolve()
    data, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    if data.size == 0:
        raise ValueError("empty vocal file")

    mono = np.mean(data, axis=1, dtype=np.float64)
    block_seconds = 0.05
    block_size = max(1, round(sample_rate * block_seconds))
    block_count = len(mono) // block_size
    if block_count == 0:
        raise ValueError("vocal file is too short")
    blocks = mono[: block_count * block_size].reshape(block_count, block_size)
    block_rms = np.sqrt(np.mean(blocks * blocks, axis=1, dtype=np.float64))
    block_db = np.full(block_rms.shape, -120.0, dtype=np.float64)
    nonzero = block_rms > 0.0
    block_db[nonzero] = 20.0 * np.log10(block_rms[nonzero])

    active_p90_dbfs = float(np.percentile(block_db, 90))
    activity_threshold_dbfs = max(-45.0, min(-30.0, active_p90_dbfs - 20.0))
    raw_phrases: list[dict[str, float]] = []
    for first_block, last_block in _phrase_regions(
        block_db, block_seconds, activity_threshold_dbfs
    ):
        first_frame = first_block * block_size
        last_frame = min(len(mono), last_block * block_size)
        phrase = mono[first_frame:last_frame]
        rms = math.sqrt(float(np.mean(phrase * phrase, dtype=np.float64)))
        if rms <= 0.0:
            continue
        raw_phrases.append(
            {
                "start_seconds": first_frame / sample_rate,
                "end_seconds": last_frame / sample_rate,
                "rms_dbfs": 20.0 * math.log10(rms),
            }
        )

    source_sha256 = _sha256(path)
    duration_seconds = len(mono) / sample_rate
    profile = _PROFILE[source_kind]
    if not raw_phrases:
        return {
            "proposal_id": hashlib.sha256(
                f"{source_sha256}:{source_kind}:empty".encode()
            ).hexdigest()[:24],
            "status": "not_needed",
            "source_kind": source_kind,
            "source_file_path": str(path),
            "source_sha256": source_sha256,
            "duration_seconds": duration_seconds,
            "phrases": [],
            "envelope_points": [],
            "activity_threshold_dbfs": activity_threshold_dbfs,
            "reason": "No sustained vocal phrases were detected above the adaptive threshold.",
        }

    target_db = float(np.median([phrase["rms_dbfs"] for phrase in raw_phrases]))
    limit_db = float(profile["limit_db"])
    strength = float(profile["strength"])
    if source_kind != "organic_multitrack":
        status = "not_recommended" if source_kind == "suno_stems" else "classify_source_first"
        identity = f"{source_sha256}:{source_kind}:{status}".encode()
        return {
            "proposal_id": hashlib.sha256(identity).hexdigest()[:24],
            "status": status,
            "source_kind": source_kind,
            "source_file_path": str(path),
            "source_sha256": source_sha256,
            "sample_rate_hz": sample_rate,
            "duration_seconds": duration_seconds,
            "activity_threshold_dbfs": activity_threshold_dbfs,
            "target_phrase_rms_dbfs": target_db,
            "maximum_correction_db": limit_db,
            "correction_strength": strength,
            "phrase_count": len(raw_phrases),
            "corrected_phrase_count": 0,
            "phrases": [
                {**phrase, "correction_db": 0.0} for phrase in raw_phrases
            ],
            "envelope_points": [],
            "time_reference": "source_file_start",
            "reason": (
                "Suno vocal stems are already processed; residual signal makes reliable "
                "phrase riding ambiguous."
                if source_kind == "suno_stems"
                else "Classify the source before applying source-dependent vocal riding."
            ),
            "verification": {
                "state": "no envelope points are emitted",
                "signal": "analysis is observational only",
                "perceptual": "use static stem balance for Suno vocals",
            },
        }
    phrases: list[dict[str, float]] = []
    point_map: dict[float, float] = {}
    for phrase in raw_phrases:
        correction = max(
            -limit_db,
            min(limit_db, (target_db - phrase["rms_dbfs"]) * strength),
        )
        if abs(correction) < 0.25:
            correction = 0.0
        correction = round(correction, 2)
        phrases.append({**phrase, "correction_db": correction})
        if correction == 0.0:
            continue
        start = phrase["start_seconds"]
        end = phrase["end_seconds"]
        point_map[round(max(0.0, start - 0.08), 6)] = 0.0
        point_map[round(start, 6)] = correction
        point_map[round(end, 6)] = correction
        point_map[round(min(duration_seconds, end + 0.12), 6)] = 0.0

    envelope_points = [
        {"source_time_seconds": time, "gain_db": gain, "shape": 0, "tension": 0.0}
        for time, gain in sorted(point_map.items())
    ]
    if len(envelope_points) > 512:
        raise ValueError("vocal rider proposal exceeds 512 envelope points")

    identity = json.dumps(
        {
            "source_sha256": source_sha256,
            "source_kind": source_kind,
            "points": envelope_points,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "proposal_id": hashlib.sha256(identity).hexdigest()[:24],
        "status": "audition_only" if envelope_points else "not_needed",
        "source_kind": source_kind,
        "source_file_path": str(path),
        "source_sha256": source_sha256,
        "sample_rate_hz": sample_rate,
        "duration_seconds": duration_seconds,
        "activity_threshold_dbfs": activity_threshold_dbfs,
        "target_phrase_rms_dbfs": target_db,
        "maximum_correction_db": limit_db,
        "correction_strength": strength,
        "phrase_count": len(phrases),
        "corrected_phrase_count": sum(
            phrase["correction_db"] != 0.0 for phrase in phrases
        ),
        "phrases": phrases,
        "envelope_points": envelope_points,
        "time_reference": "source_file_start",
        "reason": (
            "Phrase RMS is moved partway toward the median with source-aware limits."
        ),
        "verification": {
            "state": "REAPER must reread every inserted point",
            "signal": "rendered before/after comparison is still required",
            "perceptual": "listen for word endings, breaths and unnatural pumping",
        },
    }
