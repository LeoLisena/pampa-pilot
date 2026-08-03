"""Conservative WAV integrity checks, optionally scoped to a REAPER item."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Literal, Mapping


SourceKind = Literal["suno_stems", "organic_multitrack", "unknown"]

_POLICIES: dict[str, dict[str, float]] = {
    "organic_multitrack": {
        "edge_active_dbfs": -50.0,
        "boundary_sample_dbfs": -50.0,
        "click_floor": 0.12,
        "silence_dbfs": -70.0,
        "minimum_silence_seconds": 1.5,
        "suggested_fade_seconds": 0.010,
    },
    "suno_stems": {
        "edge_active_dbfs": -35.0,
        "boundary_sample_dbfs": -35.0,
        "click_floor": 0.30,
        "silence_dbfs": -80.0,
        "minimum_silence_seconds": 3.0,
        "suggested_fade_seconds": 0.005,
    },
    "unknown": {
        "edge_active_dbfs": -40.0,
        "boundary_sample_dbfs": -40.0,
        "click_floor": 0.20,
        "silence_dbfs": -70.0,
        "minimum_silence_seconds": 2.0,
        "suggested_fade_seconds": 0.005,
    },
}


def _db(value: float) -> float:
    return 20.0 * math.log10(max(value, 1e-12))


def _rms(values: Any) -> float:
    import numpy as np

    if values.size == 0:
        return 0.0
    return math.sqrt(float(np.mean(values * values, dtype=np.float64)))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regions(mask: Any, block_seconds: float) -> list[tuple[float, float]]:
    import numpy as np

    indexes = np.flatnonzero(mask)
    if indexes.size == 0:
        return []
    result: list[tuple[float, float]] = []
    first = previous = int(indexes[0])
    for raw in indexes[1:]:
        index = int(raw)
        if index != previous + 1:
            result.append((first * block_seconds, (previous + 1) * block_seconds))
            first = index
        previous = index
    result.append((first * block_seconds, (previous + 1) * block_seconds))
    return result


def _context_slice(
    data: Any,
    sample_rate: int,
    path: Path,
    item_context: Mapping[str, Any] | None,
) -> tuple[Any, float, dict[str, Any] | None]:
    if item_context is None:
        return data, 0.0, None
    loop_source = bool(item_context.get("loop_source", False))
    take = item_context.get("take")
    if not isinstance(take, Mapping):
        raise ValueError("REAPER item has no active audio take")
    observed_path = Path(str(take.get("source_path", ""))).resolve()
    if observed_path != path:
        raise ValueError("REAPER take source does not match the requested WAV")
    if str(take.get("source_type", "")).upper() == "MIDI":
        raise ValueError("REAPER item source is MIDI, not audio")
    offset = float(take.get("start_offset_seconds", 0.0))
    playrate = float(take.get("playrate", 1.0))
    item_length = float(item_context["length_seconds"])
    if offset < 0 or playrate <= 0 or item_length <= 0:
        raise ValueError("invalid REAPER item timing")
    source_end = offset + item_length * playrate
    if loop_source and source_end > len(data) / sample_rate + 1.0 / sample_rate:
        raise ValueError("REAPER item crosses a loop cycle that is not supported yet")
    if source_end > len(data) / sample_rate + 1.0 / sample_rate:
        raise ValueError("REAPER item plays beyond the analyzed source")
    first = round(offset * sample_rate)
    last = min(len(data), round(source_end * sample_rate))
    context = {
        "item_guid": item_context.get("guid"),
        "item_position_seconds": float(item_context["position_seconds"]),
        "item_length_seconds": item_length,
        "loop_source": loop_source,
        "fade_in_seconds": float(item_context.get("fade_in_seconds", 0.0)),
        "fade_out_seconds": float(item_context.get("fade_out_seconds", 0.0)),
        "take_start_offset_seconds": offset,
        "take_playrate": playrate,
        "analyzed_source_start_seconds": offset,
        "analyzed_source_end_seconds": source_end,
    }
    return data[first:last], offset, context


def analyze_audio_integrity(
    path: Path,
    source_kind: SourceKind,
    *,
    item_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Find objective edit risks without changing the WAV or REAPER."""

    import numpy as np
    import soundfile as sf

    if source_kind not in _POLICIES:
        raise ValueError(f"unsupported source kind: {source_kind}")
    path = Path(path).resolve()
    data, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    if data.size == 0:
        raise ValueError("empty audio file")
    scoped, source_offset, context = _context_slice(
        data, sample_rate, path, item_context
    )
    if len(scoped) < max(2, round(sample_rate * 0.02)):
        raise ValueError("analyzed audio span is too short")

    policy = _POLICIES[source_kind]
    mono = np.mean(scoped, axis=1, dtype=np.float64)
    absolute = np.max(np.abs(scoped), axis=1)
    duration = len(scoped) / sample_rate
    findings: list[dict[str, Any]] = []

    edge_frames = min(len(scoped), max(1, round(sample_rate * 0.02)))
    edge_start_dbfs = _db(_rms(scoped[:edge_frames]))
    edge_end_dbfs = _db(_rms(scoped[-edge_frames:]))
    first_sample_dbfs = _db(float(absolute[0]))
    last_sample_dbfs = _db(float(absolute[-1]))
    boundary_threshold = float(policy["boundary_sample_dbfs"])
    edge_threshold = float(policy["edge_active_dbfs"])

    if first_sample_dbfs >= boundary_threshold:
        findings.append(
            {
                "kind": "hard_start_boundary",
                "severity": "warning",
                "source_time_seconds": source_offset,
                "evidence": {"boundary_sample_dbfs": first_sample_dbfs},
                "interpretation": "The used audio begins away from zero and may click.",
            }
        )
    if last_sample_dbfs >= boundary_threshold:
        findings.append(
            {
                "kind": "hard_end_boundary",
                "severity": "warning",
                "source_time_seconds": source_offset + duration,
                "evidence": {"boundary_sample_dbfs": last_sample_dbfs},
                "interpretation": "The used audio ends away from zero and may click.",
            }
        )
    if edge_end_dbfs >= edge_threshold:
        findings.append(
            {
                "kind": "possible_truncated_tail",
                "severity": "review",
                "source_time_seconds": source_offset + duration,
                "evidence": {"last_20ms_rms_dbfs": edge_end_dbfs},
                "interpretation": "Audible energy reaches the end of the used source span.",
            }
        )

    differences = np.max(np.abs(np.diff(scoped, axis=0)), axis=1)
    typical = float(np.median(differences))
    percentile = float(np.percentile(differences, 99.9))
    click_threshold = max(
        float(policy["click_floor"]), typical * 50.0, percentile * 4.0
    )
    candidates = np.flatnonzero(differences >= click_threshold) + 1
    edge_guard = round(sample_rate * 0.02)
    candidates = candidates[
        (candidates >= edge_guard) & (candidates < len(scoped) - edge_guard)
    ]
    clustered_clicks: list[int] = []
    cluster_gap = max(1, round(sample_rate * 0.002))
    for raw_index in candidates:
        index = int(raw_index)
        if not clustered_clicks or index - clustered_clicks[-1] > cluster_gap:
            clustered_clicks.append(index)
        elif differences[index - 1] > differences[clustered_clicks[-1] - 1]:
            clustered_clicks[-1] = index
    for index in clustered_clicks[:128]:
        findings.append(
            {
                "kind": "impulsive_discontinuity",
                "severity": (
                    "observation" if source_kind == "suno_stems" else "review"
                ),
                "source_time_seconds": source_offset + index / sample_rate,
                "evidence": {
                    "sample_jump": float(differences[index - 1]),
                    "detection_threshold": click_threshold,
                },
                "interpretation": "An isolated sample jump may be a click or a musical transient.",
            }
        )

    block_seconds = 0.01
    block_size = max(1, round(sample_rate * block_seconds))
    block_count = len(scoped) // block_size
    blocks = scoped[: block_count * block_size].reshape(
        block_count, block_size, scoped.shape[1]
    )
    block_rms = np.sqrt(np.mean(blocks * blocks, axis=(1, 2), dtype=np.float64))
    silent = block_rms < 10.0 ** (float(policy["silence_dbfs"]) / 20.0)
    minimum_silence = float(policy["minimum_silence_seconds"])
    for start, end in _regions(silent, block_seconds):
        if start < 0.25 or end > duration - 0.25 or end - start < minimum_silence:
            continue
        findings.append(
            {
                "kind": "long_internal_silence",
                "severity": (
                    "observation" if source_kind == "suno_stems" else "review"
                ),
                "source_time_seconds": source_offset + start,
                "end_source_time_seconds": source_offset + end,
                "evidence": {
                    "duration_seconds": end - start,
                    "threshold_dbfs": float(policy["silence_dbfs"]),
                },
                "interpretation": "A long silent region inside used audio may be intentional.",
            }
        )

    clipped = np.max(np.abs(scoped), axis=1) >= 0.999969
    clipping_regions = _regions(clipped, 1.0 / sample_rate)
    flat_clipping = [region for region in clipping_regions if region[1] - region[0] >= 3 / sample_rate]
    for start, end in flat_clipping[:128]:
        findings.append(
            {
                "kind": "flat_top_clipping",
                "severity": "warning",
                "source_time_seconds": source_offset + start,
                "end_source_time_seconds": source_offset + end,
                "evidence": {"consecutive_samples": round((end - start) * sample_rate)},
                "interpretation": "At least three consecutive frames are at digital full scale.",
            }
        )

    fade_seconds = float(policy["suggested_fade_seconds"])
    suggestions: list[dict[str, Any]] = []
    kinds = {finding["kind"] for finding in findings}
    existing_in = 0.0 if context is None else context["fade_in_seconds"]
    existing_out = 0.0 if context is None else context["fade_out_seconds"]
    if "hard_start_boundary" in kinds and existing_in < fade_seconds:
        suggestions.append(
            {
                "action": "review_item_fade_in",
                "suggested_seconds": fade_seconds,
                "automatic": False,
                "reason": "A short fade may remove the hard boundary after audition.",
            }
        )
    if "hard_end_boundary" in kinds and existing_out < fade_seconds:
        suggestions.append(
            {
                "action": "review_item_fade_out",
                "suggested_seconds": fade_seconds,
                "automatic": False,
                "reason": "A short fade may remove the hard boundary after audition.",
            }
        )
    if "possible_truncated_tail" in kinds:
        suggestions.append(
            {
                "action": "review_source_tail_or_item_edge",
                "automatic": False,
                "reason": "A fade can hide a click but cannot restore missing decay.",
            }
        )

    severities = {finding["severity"] for finding in findings}
    if "warning" in severities:
        status = "review_required"
    elif "review" in severities:
        status = "review_recommended"
    elif findings:
        status = "observations_only"
    else:
        status = "no_obvious_integrity_issues"

    return {
        "schema_version": "0.1",
        "status": status,
        "source_kind": source_kind,
        "source_file_path": str(path),
        "source_sha256": _sha256(path),
        "sample_rate_hz": sample_rate,
        "channels": scoped.shape[1],
        "analyzed_duration_seconds": duration,
        "reaper_item_context": context,
        "measurements": {
            "first_sample_dbfs": first_sample_dbfs,
            "last_sample_dbfs": last_sample_dbfs,
            "first_20ms_rms_dbfs": edge_start_dbfs,
            "last_20ms_rms_dbfs": edge_end_dbfs,
            "click_detection_threshold": click_threshold,
            "candidate_click_count": len(clustered_clicks),
            "flat_top_clipping_region_count": len(flat_clipping),
        },
        "findings": findings,
        "suggestions": suggestions,
        "limitations": [
            "Impulsive musical transients can resemble clicks and require audition.",
            "Long silence can be an arrangement decision, especially in stems.",
            "Boundary energy indicates truncation risk but cannot prove missing audio.",
        ],
        "verification": {
            "state": "analysis is read-only and SHA-256-bound to the WAV",
            "signal": "findings are measurements, not confirmed audible defects",
            "perceptual": "audition every proposed repair before applying it",
        },
    }
