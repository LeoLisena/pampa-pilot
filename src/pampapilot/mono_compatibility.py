"""Read-only stereo-to-mono cancellation analysis for individual stems."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Literal

from .media_discovery import WORKSPACE_ROOT


SourceKind = Literal["suno_stems", "organic_multitrack", "unknown"]

_BANDS = {
    "sub_20_80": (20.0, 80.0),
    "bass_80_250": (80.0, 250.0),
    "low_mid_250_500": (250.0, 500.0),
    "mid_500_2000": (500.0, 2_000.0),
    "presence_2000_5000": (2_000.0, 5_000.0),
    "high_5000_12000": (5_000.0, 12_000.0),
    "air_12000_20000": (12_000.0, 20_000.0),
}


def _load_knowledge(root: Path) -> tuple[dict[str, Any], Path]:
    import yaml

    path = root / "mixing" / "mono-compatibility.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("thresholds"), dict):
        raise ValueError("mono compatibility knowledge is invalid")
    return document, path


def _db_ratio(numerator: Any, denominator: Any) -> Any:
    import numpy as np

    return 10.0 * np.log10(
        np.maximum(numerator, 1e-20) / np.maximum(denominator, 1e-20)
    )


def analyze_mono_compatibility(
    path: Path,
    source_kind: SourceKind = "unknown",
    *,
    knowledge_root: Path | None = None,
) -> dict[str, Any]:
    """Measure actual mid-energy retention by time and frequency; never write audio."""

    import numpy as np
    import soundfile as sf

    if source_kind not in {"suno_stems", "organic_multitrack", "unknown"}:
        raise ValueError("unsupported source kind")
    path = Path(path).resolve()
    root = (knowledge_root or (WORKSPACE_ROOT / "knowledge")).resolve()
    knowledge, knowledge_path = _load_knowledge(root)
    thresholds = knowledge["thresholds"]
    data, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    if data.size == 0:
        raise ValueError("empty audio file")
    if data.shape[1] != 2:
        raise ValueError("mono compatibility analysis requires exactly two channels")

    left = data[:, 0].astype(np.float64)
    right = data[:, 1].astype(np.float64)
    mid = (left + right) / 2.0
    side = (left - right) / 2.0
    block_size = max(1, round(sample_rate * 0.10))
    block_count = len(mid) // block_size
    if block_count < 2:
        raise ValueError("audio is too short for block mono analysis")
    usable = block_count * block_size
    left_blocks = left[:usable].reshape(block_count, block_size)
    right_blocks = right[:usable].reshape(block_count, block_size)
    mid_blocks = mid[:usable].reshape(block_count, block_size)
    stereo_power = np.mean(
        (left_blocks * left_blocks + right_blocks * right_blocks) / 2.0,
        axis=1,
    )
    mid_power = np.mean(mid_blocks * mid_blocks, axis=1)
    active_power = 10.0 ** (float(thresholds["active_block_dbfs"]) / 10.0)
    active = stereo_power >= active_power
    if not np.any(active):
        raise ValueError("no active blocks were detected")
    retention = _db_ratio(mid_power[active], stereo_power[active])
    p10, median, p90 = (
        float(value) for value in np.percentile(retention, [10, 50, 90])
    )
    severe_block_ratio = float(
        np.mean(retention <= float(thresholds["severe_block_retention_db"]))
    )

    fft_size = min(4096, 2 ** int(math.floor(math.log2(len(mid)))))
    fft_count = len(mid) // fft_size
    window = np.hanning(fft_size)
    left_frames = left[: fft_count * fft_size].reshape(fft_count, fft_size)
    right_frames = right[: fft_count * fft_size].reshape(fft_count, fft_size)
    mid_frames = mid[: fft_count * fft_size].reshape(fft_count, fft_size)
    total_spectrum = np.zeros(fft_size // 2 + 1, dtype=np.float64)
    mid_spectrum = np.zeros_like(total_spectrum)
    for first in range(0, fft_count, 256):
        left_fft = np.fft.rfft(left_frames[first : first + 256] * window, axis=1)
        right_fft = np.fft.rfft(right_frames[first : first + 256] * window, axis=1)
        mid_fft = np.fft.rfft(mid_frames[first : first + 256] * window, axis=1)
        total_spectrum += np.sum(
            (np.abs(left_fft) ** 2 + np.abs(right_fft) ** 2) / 2.0, axis=0
        )
        mid_spectrum += np.sum(np.abs(mid_fft) ** 2, axis=0)
    frequencies = np.fft.rfftfreq(fft_size, 1.0 / sample_rate)
    audible = (frequencies >= 20.0) & (frequencies < min(20_000.0, sample_rate / 2.0))
    audible_total = float(np.sum(total_spectrum[audible]))
    bands: list[dict[str, Any]] = []
    for name, (low_hz, high_hz) in _BANDS.items():
        mask = (frequencies >= low_hz) & (
            frequencies < min(high_hz, sample_rate / 2.0)
        )
        band_total = float(np.sum(total_spectrum[mask]))
        band_mid = float(np.sum(mid_spectrum[mask]))
        energy_ratio = band_total / audible_total if audible_total > 0.0 else 0.0
        bands.append(
            {
                "name": name,
                "low_hz": low_hz,
                "high_hz": high_hz,
                "stereo_energy_ratio": round(energy_ratio, 6),
                "mono_retention_db": round(
                    float(_db_ratio(band_mid, band_total)) if band_total > 0.0 else 0.0,
                    3,
                ),
            }
        )
    eligible_bands = [
        band
        for band in bands
        if band["stereo_energy_ratio"] >= float(thresholds["minimum_band_energy_ratio"])
    ]
    affected_bands = [
        band
        for band in eligible_bands
        if band["mono_retention_db"] <= float(thresholds["band_retention_warning_db"])
    ]

    severe = (
        median <= float(thresholds["median_retention_severe_db"])
        or severe_block_ratio >= float(thresholds["severe_block_ratio_severe"])
    )
    review = severe or (
        median <= float(thresholds["median_retention_warning_db"])
        or p10 <= float(thresholds["p10_retention_warning_db"])
        or severe_block_ratio >= float(thresholds["severe_block_ratio_warning"])
        or bool(affected_bands)
    )
    classification = "severe_cancellation" if severe else "review" if review else "compatible"
    if review:
        profile = "severe" if severe else "review"
        width_range = list(
            knowledge["recommendations"][profile]["width_audition_range_percent"]
        )
        decision = "width_reduction_audition"
        reason = "Measured time or band energy is materially reduced by mono summing."
    else:
        width_range = None
        decision = "no_change_recommended"
        reason = "No material cancellation was measured above the policy thresholds."

    source_digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            source_digest.update(block)
    digest = source_digest.hexdigest()
    identity = {
        "sha256": digest,
        "source_kind": source_kind,
        "classification": classification,
        "measurements": [round(p10, 3), round(median, 3), round(severe_block_ratio, 4)],
        "affected_bands": [band["name"] for band in affected_bands],
        "knowledge_id": knowledge["id"],
    }
    report_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]
    correlation = (
        float(np.corrcoef(left, right)[0, 1])
        if np.std(left) > 0.0 and np.std(right) > 0.0
        else None
    )
    mid_power_all = float(np.mean(mid * mid))
    side_power_all = float(np.mean(side * side))
    return {
        "schema_version": "0.1",
        "kind": "pampapilot_mono_compatibility_report",
        "report_id": report_id,
        "execute": False,
        "decision": decision,
        "classification": classification,
        "reason": reason,
        "source": {
            "file_path": str(path),
            "sha256": digest,
            "source_kind": source_kind,
            "sample_rate_hz": sample_rate,
            "channels": 2,
        },
        "measurements": {
            "stereo_correlation": correlation,
            "mono_retention_db_p10": round(p10, 3),
            "mono_retention_db_median": round(median, 3),
            "mono_retention_db_p90": round(p90, 3),
            "severe_cancellation_block_ratio": round(severe_block_ratio, 6),
            "side_to_mid_energy_db": round(
                float(_db_ratio(side_power_all, mid_power_all)), 3
            ),
            "active_block_count": int(np.count_nonzero(active)),
            "frequency_bands": bands,
            "affected_band_names": [band["name"] for band in affected_bands],
        },
        "recommendation": {
            "type": decision,
            "width_audition_range_percent": width_range,
            "source_posture": (
                "correct_observed_defect_only"
                if source_kind == "suno_stems"
                else "supervised_audition"
            ),
            "apply_automatically": False,
        },
        "knowledge": {
            "id": knowledge["id"],
            "path": str(knowledge_path),
            "confidence": knowledge["confidence"],
            "reviewed_at": str(knowledge["reviewed_at"]),
        },
        "limitations": list(knowledge["limitations"]),
        "verification": {
            "state_verified": False,
            "signal_verified": True,
            "perceptually_evaluated": False,
        },
    }
