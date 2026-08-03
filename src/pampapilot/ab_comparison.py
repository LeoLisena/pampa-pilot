"""Objective A/B preparation with attenuation-only loudness matching."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .audio_analysis import analyze_audio_file


def _gain(amplitude_db: float) -> float:
    return 10.0 ** (amplitude_db / 20.0)


def _write_matched(source: Path, destination: Path, gain_db: float) -> None:
    import soundfile as sf

    destination.parent.mkdir(parents=True, exist_ok=True)
    with sf.SoundFile(source) as input_stream:
        with sf.SoundFile(
            destination,
            mode="w",
            samplerate=input_stream.samplerate,
            channels=input_stream.channels,
            format="WAV",
            subtype="PCM_24",
        ) as output_stream:
            while True:
                block = input_stream.read(262_144, dtype="float64", always_2d=True)
                if len(block) == 0:
                    break
                output_stream.write(block * _gain(gain_db))


def build_loudness_matched_ab(
    a_file: Path,
    b_file: Path,
    a_matched_file: Path,
    b_matched_file: Path,
) -> dict[str, Any]:
    """Write comparison copies at the quieter source LUFS; originals stay untouched."""

    a_path, b_path = Path(a_file).resolve(), Path(b_file).resolve()
    a_output, b_output = Path(a_matched_file).resolve(), Path(b_matched_file).resolve()
    if a_path == b_path or a_output == b_output:
        raise ValueError("A and B paths must be distinct")
    if a_output.exists() or b_output.exists():
        raise FileExistsError("matched A/B outputs must not exist")
    a_metrics, b_metrics = analyze_audio_file(a_path), analyze_audio_file(b_path)
    if (
        a_metrics["sample_rate_hz"] != b_metrics["sample_rate_hz"]
        or a_metrics["channels"] != b_metrics["channels"]
        or a_metrics["frames"] != b_metrics["frames"]
    ):
        raise ValueError("A and B must have identical rate, channels, and duration")
    a_lufs, b_lufs = a_metrics.get("integrated_lufs"), b_metrics.get("integrated_lufs")
    if not isinstance(a_lufs, (int, float)) or not math.isfinite(a_lufs):
        raise ValueError("A integrated loudness is not measurable")
    if not isinstance(b_lufs, (int, float)) or not math.isfinite(b_lufs):
        raise ValueError("B integrated loudness is not measurable")

    target_lufs = min(float(a_lufs), float(b_lufs))
    a_gain_db, b_gain_db = target_lufs - float(a_lufs), target_lufs - float(b_lufs)
    try:
        _write_matched(a_path, a_output, a_gain_db)
        _write_matched(b_path, b_output, b_gain_db)
        a_matched = analyze_audio_file(a_output)
        b_matched = analyze_audio_file(b_output)
    except Exception:
        for path in (a_output, b_output):
            if path.is_file():
                path.unlink()
        raise

    measured_difference = abs(
        float(a_matched["integrated_lufs"]) - float(b_matched["integrated_lufs"])
    )
    identity = {
        "a": a_metrics["sha256"],
        "b": b_metrics["sha256"],
        "a_gain_db": round(a_gain_db, 6),
        "b_gain_db": round(b_gain_db, 6),
    }
    comparison_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]
    return {
        "schema_version": "0.1",
        "kind": "pampapilot_loudness_matched_ab",
        "comparison_id": comparison_id,
        "method": "integrated_lufs_attenuation_only",
        "target_lufs": target_lufs,
        "sources": {"A_original": a_metrics, "B_processed": b_metrics},
        "matched": {
            "A": {"file_path": str(a_output), "gain_db": a_gain_db, "metrics": a_matched},
            "B": {"file_path": str(b_output), "gain_db": b_gain_db, "metrics": b_matched},
        },
        "loudness_match_error_lu": measured_difference,
        "technical_match_passed": measured_difference <= 0.1,
        "listening_protocol": {
            "instruction": "Alternar A y B desde el mismo instante sin cambiar el monitor.",
            "blind_randomization": False,
            "preference_recorded": False,
        },
        "verification": {
            "signal_verified": True,
            "perceptually_evaluated": False,
            "note": "El igualado reduce el sesgo de volumen; no decide cuál versión suena mejor.",
        },
    }
