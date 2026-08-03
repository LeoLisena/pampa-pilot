"""Análisis offline de stems; nunca toca el proyecto REAPER."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable


SPECTRAL_BANDS_HZ = {
    "sub_bass_20_60": (20.0, 60.0),
    "bass_60_250": (60.0, 250.0),
    "low_mid_250_500": (250.0, 500.0),
    "mid_500_2000": (500.0, 2_000.0),
    "presence_2000_5000": (2_000.0, 5_000.0),
    "sibilance_5000_10000": (5_000.0, 10_000.0),
    "air_10000_20000": (10_000.0, 20_000.0),
}


def _db(value: float) -> float | None:
    if value <= 0.0:
        return None
    return 20.0 * math.log10(value)


def _active_dynamics(data: Any, sample_rate: int) -> dict[str, float | None]:
    import numpy as np

    mono = np.mean(data, axis=1, dtype=np.float64)
    block_size = max(1, round(sample_rate * 0.05))
    block_count = len(mono) // block_size
    if block_count == 0:
        return {
            "active_rms_dbfs_p10": None,
            "active_rms_dbfs_p50": None,
            "active_rms_dbfs_p90": None,
            "active_rms_spread_db": None,
        }
    blocks = mono[: block_count * block_size].reshape(block_count, block_size)
    block_rms = np.sqrt(np.mean(blocks * blocks, axis=1, dtype=np.float64))
    active = block_rms[block_rms >= 10.0 ** (-60.0 / 20.0)]
    if active.size == 0:
        return {
            "active_rms_dbfs_p10": None,
            "active_rms_dbfs_p50": None,
            "active_rms_dbfs_p90": None,
            "active_rms_spread_db": None,
        }
    active_db = 20.0 * np.log10(active)
    p10, p50, p90 = (float(value) for value in np.percentile(active_db, [10, 50, 90]))
    return {
        "active_rms_dbfs_p10": p10,
        "active_rms_dbfs_p50": p50,
        "active_rms_dbfs_p90": p90,
        "active_rms_spread_db": p90 - p10,
    }


def _quiet_floor(data: Any, sample_rate: int) -> dict[str, float | None]:
    """Estimate low-level passages; this is evidence, not a noise classification."""

    import numpy as np

    mono = np.mean(data, axis=1, dtype=np.float64)
    block_size = max(1, round(sample_rate * 0.05))
    block_count = len(mono) // block_size
    if block_count == 0:
        return {
            "quiet_block_ratio_below_minus_40_dbfs": None,
            "quiet_rms_dbfs_p90_below_minus_40": None,
        }
    blocks = mono[: block_count * block_size].reshape(block_count, block_size)
    block_rms = np.sqrt(np.mean(blocks * blocks, axis=1, dtype=np.float64))
    block_db = np.full(block_rms.shape, -120.0, dtype=np.float64)
    audible = block_rms > 0.0
    block_db[audible] = 20.0 * np.log10(block_rms[audible])
    quiet = block_db[block_db < -40.0]
    return {
        "quiet_block_ratio_below_minus_40_dbfs": float(np.mean(block_db < -40.0)),
        "quiet_rms_dbfs_p90_below_minus_40": (
            float(np.percentile(quiet, 90)) if quiet.size else None
        ),
    }


def _spectral_metrics(data: Any, sample_rate: int) -> dict[str, Any]:
    import numpy as np

    mono = np.mean(data, axis=1, dtype=np.float64)
    if len(mono) < 64:
        return {
            "spectral_band_energy_ratio": {name: 0.0 for name in SPECTRAL_BANDS_HZ},
            "spectral_centroid_hz": None,
            "spectral_flatness": None,
            "sibilance_ratio_p95": None,
            "low_frequency_ratio_below_100_hz_p95": None,
        }
    fft_size = min(4096, 2 ** int(math.floor(math.log2(len(mono)))))
    frame_count = len(mono) // fft_size
    frames = mono[: frame_count * fft_size].reshape(frame_count, fft_size)
    window = np.hanning(fft_size)
    frequencies = np.fft.rfftfreq(fft_size, 1.0 / sample_rate)
    accumulated = np.zeros(len(frequencies), dtype=np.float64)
    sibilance_ratios: list[float] = []
    low_ratios: list[float] = []
    audible_mask = (frequencies >= 20.0) & (frequencies < min(20_000.0, sample_rate / 2.0))
    speech_mask = (frequencies >= 1_000.0) & (frequencies < min(10_000.0, sample_rate / 2.0))
    sibilance_mask = (frequencies >= 5_000.0) & (frequencies < min(10_000.0, sample_rate / 2.0))
    low_mask = (frequencies >= 20.0) & (frequencies < min(100.0, sample_rate / 2.0))
    for first in range(0, frame_count, 256):
        batch = frames[first : first + 256] * window
        power = np.abs(np.fft.rfft(batch, axis=1)) ** 2
        accumulated += np.sum(power, axis=0)
        audible_power = np.sum(power[:, audible_mask], axis=1)
        low_power = np.sum(power[:, low_mask], axis=1)
        valid_audible = audible_power > 0.0
        low_ratios.extend((low_power[valid_audible] / audible_power[valid_audible]).tolist())
        speech_power = np.sum(power[:, speech_mask], axis=1)
        sibilance_power = np.sum(power[:, sibilance_mask], axis=1)
        valid_speech = speech_power > 0.0
        sibilance_ratios.extend(
            (sibilance_power[valid_speech] / speech_power[valid_speech]).tolist()
        )

    total = float(np.sum(accumulated[audible_mask]))
    ratios: dict[str, float] = {}
    for name, (minimum, maximum) in SPECTRAL_BANDS_HZ.items():
        mask = (frequencies >= minimum) & (
            frequencies < min(maximum, sample_rate / 2.0)
        )
        ratios[name] = float(np.sum(accumulated[mask]) / total) if total > 0.0 else 0.0
    audible_power = accumulated[audible_mask]
    audible_frequencies = frequencies[audible_mask]
    centroid = (
        float(np.sum(audible_frequencies * audible_power) / np.sum(audible_power))
        if audible_power.size and np.sum(audible_power) > 0.0
        else None
    )
    positive_power = audible_power[audible_power > 0.0]
    flatness = (
        float(np.exp(np.mean(np.log(positive_power))) / np.mean(positive_power))
        if positive_power.size
        else None
    )
    return {
        "spectral_band_energy_ratio": ratios,
        "spectral_centroid_hz": centroid,
        "spectral_flatness": flatness,
        "sibilance_ratio_p95": (
            float(np.percentile(sibilance_ratios, 95)) if sibilance_ratios else None
        ),
        "low_frequency_ratio_below_100_hz_p95": (
            float(np.percentile(low_ratios, 95)) if low_ratios else None
        ),
    }


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
    active_dynamics = _active_dynamics(data, sample_rate)
    quiet_floor = _quiet_floor(data, sample_rate)
    spectral = _spectral_metrics(data, sample_rate)

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
        **active_dynamics,
        **quiet_floor,
        **spectral,
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
