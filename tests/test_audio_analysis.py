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
    assert result["active_rms_spread_db"] == pytest.approx(0.0, abs=0.01)
    assert result["spectral_centroid_hz"] == pytest.approx(440.0, abs=3.0)
    assert result["spectral_band_energy_ratio"]["low_mid_250_500"] > 0.99


def test_write_analysis_creates_utf8_json(tmp_path: Path) -> None:
    audio_path = tmp_path / "señal.wav"
    output_path = tmp_path / "analysis" / "stems.json"
    _write_test_tone(audio_path)

    write_analysis(analyze_stems([audio_path]), output_path)
    stored = json.loads(output_path.read_text(encoding="utf-8"))

    assert stored["schema_version"] == "0.1"
    assert stored["metrics_are_observations_not_mix_decisions"] is True
    assert stored["stems"][0]["file_name"] == "señal.wav"


def test_analysis_measures_quiet_floor_without_calling_it_noise(tmp_path: Path) -> None:
    sample_rate = 48_000
    rng = np.random.default_rng(7)
    quiet = rng.normal(0.0, 0.001, sample_rate).astype(np.float32)
    time = np.arange(sample_rate, dtype=np.float32) / sample_rate
    active = 0.2 * np.sin(2.0 * np.pi * 220.0 * time)
    mono = np.concatenate((quiet, active))
    path = tmp_path / "quiet-and-active.wav"
    sf.write(path, np.column_stack((mono, mono)), sample_rate, subtype="FLOAT")

    result = analyze_audio_file(path)

    assert result["quiet_block_ratio_below_minus_40_dbfs"] == pytest.approx(0.5)
    assert result["quiet_rms_dbfs_p90_below_minus_40"] == pytest.approx(-60.0, abs=1.0)
    assert result["active_rms_dbfs_p90"] > -20.0


def test_analysis_measures_intermittent_sibilance_band_level(tmp_path: Path) -> None:
    sample_rate = 48_000
    duration = 2.0
    time = np.arange(round(sample_rate * duration), dtype=np.float32) / sample_rate
    mono = 0.05 * np.sin(2.0 * np.pi * 220.0 * time)
    burst = (time >= 1.6).astype(np.float32)
    mono += burst * 0.25 * np.sin(2.0 * np.pi * 7_000.0 * time)
    path = tmp_path / "synthetic-sibilance.wav"
    sf.write(path, np.column_stack((mono, mono)), sample_rate, subtype="FLOAT")

    result = analyze_audio_file(path)

    assert result["sibilance_ratio_p95"] > 0.9
    assert result["sibilance_band_rms_dbfs_p95"] == pytest.approx(-15.05, abs=0.5)
    assert result["sibilance_peak_to_median_db"] > 40.0
