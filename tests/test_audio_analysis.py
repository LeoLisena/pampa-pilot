from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from pampapilot.audio_analysis import analyze_audio_file, analyze_stems, write_analysis


def _write_test_tone(path: Path) -> None:
    sample_rate = 48_000
    time = np.arange(sample_rate, dtype=np.float32) / sample_rate
    mono = 0.5 * np.sin(2.0 * np.pi * 440.0 * time)
    sf.write(path, np.column_stack((mono, mono)), sample_rate, subtype="FLOAT")


def test_analyze_audio_file_reports_objective_signal_metrics(tmp_path: Path) -> None:
    audio_path = tmp_path / "tone.wav"
    _write_test_tone(audio_path)

    result = analyze_audio_file(audio_path)

    assert result["sample_rate_hz"] == 48_000
    assert result["channels"] == 2
    assert result["duration_seconds"] == 1.0
    assert result["sample_peak_dbfs"] == pytest.approx(-6.0206, abs=0.01)
    assert result["samples_at_or_above_0_dbfs"] == 0
    assert result["stereo_correlation"] == pytest.approx(1.0)
    assert len(result["sha256"]) == 64


def test_write_analysis_creates_utf8_json(tmp_path: Path) -> None:
    audio_path = tmp_path / "señal.wav"
    output_path = tmp_path / "analysis" / "stems.json"
    _write_test_tone(audio_path)

    write_analysis(analyze_stems([audio_path]), output_path)
    stored = json.loads(output_path.read_text(encoding="utf-8"))

    assert stored["schema_version"] == "0.1"
    assert stored["metrics_are_observations_not_mix_decisions"] is True
    assert stored["stems"][0]["file_name"] == "señal.wav"
