from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from pampapilot.mono_compatibility import analyze_mono_compatibility


SAMPLE_RATE = 48_000


def _tone() -> np.ndarray:
    time = np.arange(SAMPLE_RATE, dtype=np.float32) / SAMPLE_RATE
    return (0.2 * np.sin(2.0 * np.pi * 440.0 * time)).astype(np.float32)


def test_coherent_stereo_needs_no_width_change(tmp_path: Path) -> None:
    tone = _tone()
    path = tmp_path / "coherent.wav"
    sf.write(path, np.column_stack((tone, tone)), SAMPLE_RATE, subtype="FLOAT")

    report = analyze_mono_compatibility(path, "suno_stems")

    assert report["classification"] == "compatible"
    assert report["decision"] == "no_change_recommended"
    assert report["measurements"]["mono_retention_db_median"] == pytest.approx(0.0)
    assert report["recommendation"]["width_audition_range_percent"] is None
    assert report["execute"] is False


def test_antiphase_stereo_is_detected_as_severe(tmp_path: Path) -> None:
    tone = _tone()
    path = tmp_path / "antiphase.wav"
    sf.write(path, np.column_stack((tone, -tone)), SAMPLE_RATE, subtype="FLOAT")

    report = analyze_mono_compatibility(path, "organic_multitrack")

    assert report["classification"] == "severe_cancellation"
    assert report["decision"] == "width_reduction_audition"
    assert report["measurements"]["severe_cancellation_block_ratio"] == 1.0
    assert report["recommendation"]["width_audition_range_percent"] == [70, 90]
    assert report["recommendation"]["apply_automatically"] is False


def test_mono_source_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "mono.wav"
    sf.write(path, _tone(), SAMPLE_RATE, subtype="FLOAT")
    with pytest.raises(ValueError, match="exactly two channels"):
        analyze_mono_compatibility(path)
