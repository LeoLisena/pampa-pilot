from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from pampapilot.ab_comparison import build_loudness_matched_ab


def test_ab_matching_only_attenuates_louder_version(tmp_path: Path) -> None:
    sample_rate = 48_000
    time = np.arange(sample_rate * 3, dtype=np.float64) / sample_rate
    quiet = 0.08 * np.sin(2 * np.pi * 440.0 * time)
    loud = quiet * 2.0
    a, b = tmp_path / "A.wav", tmp_path / "B.wav"
    a_match, b_match = tmp_path / "A-match.wav", tmp_path / "B-match.wav"
    sf.write(a, np.column_stack((quiet, quiet)), sample_rate, subtype="PCM_24")
    sf.write(b, np.column_stack((loud, loud)), sample_rate, subtype="PCM_24")

    report = build_loudness_matched_ab(a, b, a_match, b_match)

    assert report["matched"]["A"]["gain_db"] == 0.0
    assert report["matched"]["B"]["gain_db"] < -5.9
    assert report["technical_match_passed"]
    assert report["loudness_match_error_lu"] <= 0.1
    assert a_match.is_file() and b_match.is_file()


def test_ab_matching_rejects_silent_input(tmp_path: Path) -> None:
    a, b = tmp_path / "A.wav", tmp_path / "B.wav"
    silence = np.zeros((48_000, 2), dtype=np.float32)
    time = np.arange(48_000, dtype=np.float64) / 48_000
    mono = (0.1 * np.sin(2 * np.pi * 440.0 * time)).astype(np.float32)
    tone = np.column_stack((mono, mono))
    sf.write(a, silence, 48_000, subtype="PCM_24")
    sf.write(b, tone, 48_000, subtype="PCM_24")

    with pytest.raises(ValueError, match="A integrated loudness"):
        build_loudness_matched_ab(
            a, b, tmp_path / "A-match.wav", tmp_path / "B-match.wav"
        )
