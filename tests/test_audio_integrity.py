from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from pampapilot.audio_integrity import analyze_audio_integrity


SAMPLE_RATE = 48_000


def _write(path: Path, mono: np.ndarray) -> None:
    sf.write(path, mono.astype(np.float32), SAMPLE_RATE, subtype="FLOAT")


def _windowed_tone(seconds: float, amplitude: float = 0.1) -> np.ndarray:
    frames = round(SAMPLE_RATE * seconds)
    time = np.arange(frames, dtype=np.float64) / SAMPLE_RATE
    return amplitude * np.sin(2 * np.pi * 220.0 * time) * np.hanning(frames)


def test_clean_windowed_audio_has_no_obvious_integrity_issues(tmp_path: Path) -> None:
    path = tmp_path / "clean.wav"
    _write(path, _windowed_tone(1.0))

    report = analyze_audio_integrity(path, "organic_multitrack")

    assert report["status"] == "no_obvious_integrity_issues"
    assert report["findings"] == []
    assert len(report["source_sha256"]) == 64


def test_detects_impulse_internal_silence_clipping_and_live_tail(tmp_path: Path) -> None:
    path = tmp_path / "damaged.wav"
    first = _windowed_tone(0.75, 0.05)
    first[round(0.4 * SAMPLE_RATE)] = 0.8
    silence = np.zeros(round(1.6 * SAMPLE_RATE))
    tail = np.full(round(0.65 * SAMPLE_RATE), 1.0)
    _write(path, np.concatenate((first, silence, tail)))

    report = analyze_audio_integrity(path, "organic_multitrack")
    kinds = {finding["kind"] for finding in report["findings"]}

    assert report["status"] == "review_required"
    assert "impulsive_discontinuity" in kinds
    assert "long_internal_silence" in kinds
    assert "hard_end_boundary" in kinds
    assert "possible_truncated_tail" in kinds
    assert "flat_top_clipping" in kinds
    assert all(suggestion["automatic"] is False for suggestion in report["suggestions"])


def test_suno_boundary_policy_is_more_conservative(tmp_path: Path) -> None:
    path = tmp_path / "processed.wav"
    audio = _windowed_tone(1.0)
    audio[0] = 0.01
    _write(path, audio)

    organic = analyze_audio_integrity(path, "organic_multitrack")
    suno = analyze_audio_integrity(path, "suno_stems")

    assert "hard_start_boundary" in {x["kind"] for x in organic["findings"]}
    assert "hard_start_boundary" not in {x["kind"] for x in suno["findings"]}


def test_suno_transients_are_observations_not_defects(tmp_path: Path) -> None:
    path = tmp_path / "suno-percussion.wav"
    audio = _windowed_tone(5.0, 0.05)
    audio[round(0.8 * SAMPLE_RATE)] = 0.9
    audio[round(1.0 * SAMPLE_RATE) : round(4.2 * SAMPLE_RATE)] = 0.0
    _write(path, audio)

    report = analyze_audio_integrity(path, "suno_stems")

    assert report["status"] == "observations_only"
    assert report["findings"]
    assert {finding["severity"] for finding in report["findings"]} == {
        "observation"
    }


def test_reaper_context_scopes_analysis_and_preserves_fades(tmp_path: Path) -> None:
    path = (tmp_path / "source.wav").resolve()
    audio = np.concatenate(
        (
            np.full(SAMPLE_RATE, 0.2),
            _windowed_tone(1.0),
            np.full(SAMPLE_RATE, 0.2),
        )
    )
    _write(path, audio)
    context = {
        "guid": "{ITEM}",
        "position_seconds": 12.0,
        "length_seconds": 1.0,
        "loop_source": False,
        "fade_in_seconds": 0.01,
        "fade_out_seconds": 0.02,
        "take": {
            "source_path": str(path),
            "source_type": "WAVE",
            "start_offset_seconds": 1.0,
            "playrate": 1.0,
        },
    }

    report = analyze_audio_integrity(
        path, "organic_multitrack", item_context=context
    )

    assert report["status"] == "no_obvious_integrity_issues"
    assert report["analyzed_duration_seconds"] == pytest.approx(1.0)
    assert report["reaper_item_context"]["analyzed_source_start_seconds"] == 1.0
    assert report["reaper_item_context"]["fade_out_seconds"] == 0.02


def test_rejects_mismatched_reaper_source(tmp_path: Path) -> None:
    path = (tmp_path / "source.wav").resolve()
    _write(path, _windowed_tone(1.0))
    context = {
        "length_seconds": 1.0,
        "position_seconds": 0.0,
        "take": {
            "source_path": str(tmp_path / "other.wav"),
            "source_type": "WAVE",
            "start_offset_seconds": 0.0,
            "playrate": 1.0,
        },
    }

    with pytest.raises(ValueError, match="does not match"):
        analyze_audio_integrity(path, "organic_multitrack", item_context=context)


def test_rejects_looped_reaper_item_only_when_it_crosses_a_cycle(
    tmp_path: Path,
) -> None:
    path = (tmp_path / "source.wav").resolve()
    _write(path, _windowed_tone(1.0))

    with pytest.raises(ValueError, match="loop cycle"):
        analyze_audio_integrity(
            path,
            "organic_multitrack",
            item_context={
                "guid": "{LOOPED}",
                "position_seconds": 0.0,
                "length_seconds": 2.0,
                "loop_source": True,
                "take": {
                    "source_path": str(path),
                    "source_type": "WAVE",
                    "start_offset_seconds": 0.0,
                    "playrate": 1.0,
                },
            },
        )
