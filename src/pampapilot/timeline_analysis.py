"""Reusable, DAW-independent musical timeline analysis for aligned stems."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
import unicodedata


ANALYSIS_VERSION = "0.1"
_ROLE_PATTERNS = (
    ("backing_vocals", re.compile(r"\b(backing|back|coral|choir|coro)\b")),
    ("lead_vocal", re.compile(r"\b(vocal|vocals|voice|voz)\b")),
    ("drums", re.compile(r"\b(drum|drums|percussion|percusion|bateria)\b")),
    ("bass", re.compile(r"\b(bass|bajo)\b")),
    ("guitar", re.compile(r"\b(guitar|guitarra)\b")),
    ("keys", re.compile(r"\b(keyboard|keys|piano|synth|sintetizador)\b")),
    ("strings", re.compile(r"\b(strings|string|cuerdas|violin|cello)\b")),
)


def _normalized_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"^\s*\d+\s*[-_. ]*", "", normalized)
    return " ".join(re.findall(r"[^\W_]+", normalized, flags=re.UNICODE))


def infer_stem_role(path: Path) -> str:
    """Infer a broad production role without depending on track order."""

    name = _normalized_name(Path(path).stem)
    for role, pattern in _ROLE_PATTERNS:
        if pattern.search(name):
            return role
    return "other"


def _robust_standardize(values: Any, *, axis: int = 0) -> Any:
    import numpy as np

    values = np.asarray(values, dtype=np.float64)
    median = np.median(values, axis=axis, keepdims=True)
    scale = np.median(np.abs(values - median), axis=axis, keepdims=True)
    # A silent or nearly constant feature contains no discriminating evidence.
    # Mapping its microscopic numerical noise to enormous z-scores would make
    # a silent stem dominate the ensemble, so such dimensions deliberately
    # contribute zero.
    denominator = np.where(scale > 1e-6, scale * 1.4826, np.inf)
    return np.clip((values - median) / denominator, -8.0, 8.0)


def _grid(duration: float, bpm: float, downbeats: Iterable[float] | None) -> list[float]:
    import numpy as np

    if not 20.0 <= bpm <= 400.0:
        raise ValueError("bpm must be between 20 and 400")
    if downbeats is None:
        points = np.arange(0.0, duration, 240.0 / bpm).tolist()
    else:
        points = [0.0, *(float(value) for value in downbeats)]
    points = sorted({round(value, 6) for value in points if 0.0 <= value < duration})
    if not points or points[0] > 1e-6:
        points.insert(0, 0.0)
    if duration - points[-1] < 0.08:
        points[-1] = duration
    else:
        points.append(duration)
    if len(points) < 3:
        raise ValueError("timeline needs at least two musical intervals")
    return points


def _aggregate_frames(feature: Any, frame_times: Any, boundaries: Any) -> Any:
    import numpy as np

    feature = np.asarray(feature, dtype=np.float64)
    if feature.ndim == 1:
        feature = feature[None, :]
    result = np.zeros((len(boundaries) - 1, feature.shape[0]), dtype=np.float64)
    for index, (start, end) in enumerate(zip(boundaries[:-1], boundaries[1:])):
        mask = (frame_times >= start) & (frame_times < end)
        if not np.any(mask):
            frame = min(len(frame_times) - 1, max(0, int(np.searchsorted(frame_times, start))))
            result[index] = feature[:, frame]
        else:
            result[index] = np.mean(feature[:, mask], axis=1)
    return result


def _analyze_stem(path: Path, boundaries: Any, analysis_sample_rate: int) -> dict[str, Any]:
    import librosa
    import numpy as np

    signal, sample_rate = librosa.load(path, sr=analysis_sample_rate, mono=True)
    hop_length = 256
    n_fft = 2048
    rms = librosa.feature.rms(y=signal, frame_length=n_fft, hop_length=hop_length)[0]
    onset = librosa.onset.onset_strength(y=signal, sr=sample_rate, hop_length=hop_length)
    centroid = librosa.feature.spectral_centroid(
        y=signal, sr=sample_rate, n_fft=n_fft, hop_length=hop_length
    )[0] / (sample_rate / 2.0)
    bandwidth = librosa.feature.spectral_bandwidth(
        y=signal, sr=sample_rate, n_fft=n_fft, hop_length=hop_length
    )[0] / (sample_rate / 2.0)
    rolloff = librosa.feature.spectral_rolloff(
        y=signal, sr=sample_rate, n_fft=n_fft, hop_length=hop_length, roll_percent=0.85
    )[0] / (sample_rate / 2.0)
    chroma = librosa.feature.chroma_stft(
        y=signal, sr=sample_rate, n_fft=n_fft, hop_length=hop_length
    )
    frame_count = min(len(rms), len(onset), len(centroid), len(bandwidth), len(rolloff), chroma.shape[1])
    frame_times = librosa.frames_to_time(
        np.arange(frame_count), sr=sample_rate, hop_length=hop_length
    )
    rms = rms[:frame_count]
    rms_db = 20.0 * np.log10(np.maximum(rms, 1e-9))
    activity_threshold = max(-55.0, float(np.percentile(rms_db, 25)) + 10.0)
    activity = (rms_db >= activity_threshold).astype(np.float64)
    scalar = np.vstack(
        (
            rms_db,
            onset[:frame_count],
            centroid[:frame_count],
            bandwidth[:frame_count],
            rolloff[:frame_count],
            activity,
        )
    )
    scalar_bars = _aggregate_frames(scalar, frame_times, boundaries)
    chroma_bars = _aggregate_frames(chroma[:, :frame_count], frame_times, boundaries)
    chroma_norm = chroma_bars / np.maximum(np.linalg.norm(chroma_bars, axis=1, keepdims=True), 1e-9)
    embedding = np.column_stack((scalar_bars, chroma_norm))
    standardized = _robust_standardize(embedding, axis=0)
    return {
        "path": str(path.resolve()),
        "file_name": path.name,
        "role": infer_stem_role(path),
        "duration_seconds": len(signal) / sample_rate,
        "activity_threshold_dbfs": activity_threshold,
        "bar_features": {
            "rms_dbfs": scalar_bars[:, 0].round(5).tolist(),
            "onset_strength": scalar_bars[:, 1].round(5).tolist(),
            "spectral_centroid_ratio": scalar_bars[:, 2].round(6).tolist(),
            "spectral_bandwidth_ratio": scalar_bars[:, 3].round(6).tolist(),
            "spectral_rolloff_ratio": scalar_bars[:, 4].round(6).tolist(),
            "active_ratio": scalar_bars[:, 5].round(6).tolist(),
            "chroma": chroma_norm.round(6).tolist(),
        },
        "standardized_embedding": standardized.round(6).tolist(),
    }


def _boundary_evidence(stems: list[dict[str, Any]], boundaries: list[float]) -> list[dict[str, Any]]:
    import numpy as np

    matrices = [np.asarray(stem["standardized_embedding"], dtype=np.float64) for stem in stems]
    raw = np.zeros((len(stems), len(boundaries) - 2), dtype=np.float64)
    energy_delta = np.zeros_like(raw)
    for stem_index, (stem, matrix) in enumerate(zip(stems, matrices)):
        rms = np.asarray(stem["bar_features"]["rms_dbfs"], dtype=np.float64)
        for boundary_index in range(1, len(boundaries) - 1):
            left = matrix[max(0, boundary_index - 2):boundary_index].mean(axis=0)
            right = matrix[boundary_index:min(len(matrix), boundary_index + 2)].mean(axis=0)
            raw[stem_index, boundary_index - 1] = float(
                np.linalg.norm(right - left) / math.sqrt(matrix.shape[1])
            )
            energy_delta[stem_index, boundary_index - 1] = float(
                rms[boundary_index:min(len(rms), boundary_index + 2)].mean()
                - rms[max(0, boundary_index - 2):boundary_index].mean()
            )
    normalized = _robust_standardize(raw, axis=1)
    role_indexes: dict[str, list[int]] = {}
    for index, stem in enumerate(stems):
        role_indexes.setdefault(stem["role"], []).append(index)
    result = []
    for index, time_seconds in enumerate(boundaries[1:-1]):
        stem_changes = {
            stem["file_name"]: round(float(raw[stem_index, index]), 5)
            for stem_index, stem in enumerate(stems)
        }
        role_changes = {
            role: round(float(np.mean(raw[indexes, index])), 5)
            for role, indexes in role_indexes.items()
        }
        role_energy_delta = {
            role: round(float(np.mean(energy_delta[indexes, index])), 5)
            for role, indexes in role_indexes.items()
        }
        # Consensus is role-balanced: four alternative drum stems must not get
        # four votes against one vocal or bass stem.
        role_normalized = {
            role: float(np.mean(normalized[indexes, index]))
            for role, indexes in role_indexes.items()
        }
        consensus = float(np.mean([value >= 0.5 for value in role_normalized.values()]))
        result.append(
            {
                "time_seconds": time_seconds,
                "multistem_change": round(float(np.median(list(role_changes.values()))), 5),
                "change_consensus": round(consensus, 5),
                "stem_changes": stem_changes,
                "role_changes": role_changes,
                "role_energy_delta_db": role_energy_delta,
            }
        )
    return result


def analyze_music_timeline(
    stem_paths: Iterable[Path],
    *,
    bpm: float,
    downbeats: Iterable[float] | None = None,
    analysis_sample_rate: int = 11_025,
) -> dict[str, Any]:
    """Measure aligned stems on musical intervals for reuse by producer features."""

    import soundfile as sf

    paths = [Path(path).resolve() for path in stem_paths]
    if not paths:
        raise ValueError("at least one stem is required")
    durations = [sf.info(path).duration for path in paths]
    duration = max(durations)
    if max(durations) - min(durations) > 0.1:
        raise ValueError("stems are not time-aligned: duration difference exceeds 100 ms")
    boundaries = _grid(duration, bpm, downbeats)
    stems = [_analyze_stem(path, boundaries, analysis_sample_rate) for path in paths]
    return {
        "schema_version": "0.1",
        "kind": "pampapilot_music_timeline_analysis",
        "analysis_version": ANALYSIS_VERSION,
        "analyzed_at_utc": datetime.now(UTC).isoformat(),
        "bpm": bpm,
        "duration_seconds": duration,
        "analysis_sample_rate_hz": analysis_sample_rate,
        "grid_source": "external_downbeats" if downbeats is not None else "tempo_4_4",
        "interval_boundaries_seconds": boundaries,
        "stems": stems,
        "boundary_evidence": _boundary_evidence(stems, boundaries),
        "reuse_contract": {
            "observations_not_mix_decisions": True,
            "possible_consumers": [
                "song_structure",
                "static_balance",
                "dynamic_processing",
                "eq_proposals",
                "silence_and_leak_detection",
                "automation",
            ],
        },
    }


def write_music_timeline_analysis(report: Mapping[str, Any], output_path: Path) -> None:
    """Persist an analysis artifact without coupling consumers to Python objects."""

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
