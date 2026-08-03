from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from pampapilot.timeline_analysis import analyze_music_timeline, infer_stem_role


def _stem(path: Path, amplitudes: tuple[float, ...], sample_rate: int = 8_000) -> None:
    parts = []
    for index, amplitude in enumerate(amplitudes):
        time = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
        parts.append(amplitude * np.sin(2 * np.pi * (180 + index * 35) * time))
    sf.write(path, np.concatenate(parts), sample_rate)


def test_role_inference_is_independent_from_numeric_prefix() -> None:
    assert infer_stem_role(Path("10 Vocals.wav")) == "lead_vocal"
    assert infer_stem_role(Path("9 Backing_Vocals.wav")) == "backing_vocals"
    assert infer_stem_role(Path("6 Drums- OK.wav")) == "drums"
    assert infer_stem_role(Path("0 Synth.wav")) == "keys"


def test_timeline_analysis_exposes_reusable_per_stem_and_boundary_features(
    tmp_path: Path,
) -> None:
    vocal, drums = tmp_path / "10 Vocals.wav", tmp_path / "5 Drums.wav"
    _stem(vocal, (0.0, 0.03, 0.12, 0.12))
    _stem(drums, (0.02, 0.02, 0.1, 0.1))

    report = analyze_music_timeline(
        [vocal, drums], bpm=120.0, downbeats=[2.0, 4.0, 6.0]
    )

    assert report["grid_source"] == "external_downbeats"
    assert report["interval_boundaries_seconds"] == pytest.approx([0, 2, 4, 6, 8])
    assert [stem["role"] for stem in report["stems"]] == ["lead_vocal", "drums"]
    assert len(report["stems"][0]["bar_features"]["chroma"]) == 4
    assert len(report["boundary_evidence"]) == 3
    assert report["reuse_contract"]["observations_not_mix_decisions"] is True


def test_timeline_analysis_rejects_unaligned_stems(tmp_path: Path) -> None:
    short, long = tmp_path / "short.wav", tmp_path / "long.wav"
    _stem(short, (0.1, 0.1))
    _stem(long, (0.1, 0.1, 0.1))
    with pytest.raises(ValueError, match="not time-aligned"):
        analyze_music_timeline([short, long], bpm=120.0)
