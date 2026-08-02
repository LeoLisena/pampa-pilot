"""Análisis offline de stems; nunca toca el proyecto REAPER."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable


def _db(value: float) -> float | None:
    if value <= 0.0:
        return None
    return 20.0 * math.log10(value)


def analyze_audio_file(path: Path) -> dict[str, Any]:
    """Mide propiedades objetivas de un WAV completo."""

    import numpy as np
    import pyloudnorm as pyln
    import soundfile as sf

    info = sf.info(path)
    data, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    if data.size == 0:
        raise ValueError(f"archivo sin muestras: {path}")

    absolute = np.abs(data)
    frame_peak = np.max(absolute, axis=1)
    sample_peak = float(np.max(absolute))
    rms = float(math.sqrt(float(np.einsum("ij,ij->", data, data, dtype=np.float64)) / data.size))
    channel_peaks = np.max(absolute, axis=0)
    channel_rms = np.sqrt(
        np.einsum("ij,ij->j", data, data, dtype=np.float64) / len(data)
    )
    dc_offset = np.mean(data, axis=0, dtype=np.float64)
    silence_threshold = 10.0 ** (-60.0 / 20.0)
    active_indexes = np.flatnonzero(frame_peak >= silence_threshold)
    integrated_lufs = float(pyln.Meter(sample_rate).integrated_loudness(data))
    channel_correlation = None
    if data.shape[1] == 2 and np.std(data[:, 0]) > 0 and np.std(data[:, 1]) > 0:
        channel_correlation = float(np.corrcoef(data[:, 0], data[:, 1])[0, 1])

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)

    return {
        "file_name": path.name,
        "file_path": str(path.resolve()),
        "sha256": digest.hexdigest(),
        "sample_rate_hz": sample_rate,
        "channels": data.shape[1],
        "frames": len(data),
        "duration_seconds": len(data) / sample_rate,
        "format": info.format,
        "subtype": info.subtype,
        "integrated_lufs": integrated_lufs if math.isfinite(integrated_lufs) else None,
        "sample_peak_dbfs": _db(sample_peak),
        "rms_dbfs": _db(rms),
        "crest_factor_db": _db(sample_peak) - _db(rms) if sample_peak > 0 and rms > 0 else None,
        "channel_peak_dbfs": [_db(float(value)) for value in channel_peaks],
        "channel_rms_dbfs": [_db(float(value)) for value in channel_rms],
        "dc_offset": [float(value) for value in dc_offset],
        "stereo_correlation": channel_correlation,
        "samples_at_or_above_0_dbfs": int(np.count_nonzero(absolute >= 1.0)),
        "near_silence_ratio_below_minus_60_dbfs": float(np.mean(frame_peak < silence_threshold)),
        "active_start_seconds": float(active_indexes[0] / sample_rate) if active_indexes.size else None,
        "active_end_seconds": float((active_indexes[-1] + 1) / sample_rate) if active_indexes.size else None,
    }


def analyze_stems(paths: Iterable[Path]) -> dict[str, Any]:
    ordered = [Path(path) for path in paths]
    return {
        "schema_version": "0.1",
        "analyzed_at_utc": datetime.now(UTC).isoformat(),
        "metrics_are_observations_not_mix_decisions": True,
        "stems": [analyze_audio_file(path) for path in ordered],
    }


def write_analysis(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
