from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from pampapilot.mastering_qc import (
    build_master_delivery_qc,
    build_project_master_delivery_qc,
)


KNOWLEDGE_ROOT = Path(__file__).resolve().parents[1] / "knowledge"


def _write_tone(path: Path, amplitude: float, *, channels: int = 2) -> None:
    sample_rate = 48_000
    time = np.arange(sample_rate * 4, dtype=np.float64) / sample_rate
    mono = amplitude * np.sin(2.0 * np.pi * 997.0 * time + 0.37)
    data = mono if channels == 1 else np.column_stack([mono] * channels)
    sf.write(path, data, sample_rate, subtype="PCM_24")


def test_qc_is_read_only_and_reports_normalization_and_true_peak(tmp_path: Path) -> None:
    audio_path = tmp_path / "master.wav"
    _write_tone(audio_path, 0.5)
    before = audio_path.read_bytes()

    report = build_master_delivery_qc(audio_path, knowledge_root=KNOWLEDGE_ROOT)

    assert audio_path.read_bytes() == before
    assert report["execute"] is False
    assert report["measurements"]["channels"] == 2
    assert report["measurements"]["sample_rate_hz"] == 48_000
    assert report["measurements"]["estimated_true_peak_dbtp"] >= (
        report["measurements"]["sample_peak_dbfs"] - 0.02
    )
    assert report["normalization_scenarios"]["normal"]["requested_gain_db"] < 0
    assert report["verification"]["signal_verified"] is True
    assert len(report["report_id"]) == 24


def test_qc_warns_for_non_stereo_delivery(tmp_path: Path) -> None:
    audio_path = tmp_path / "mono.wav"
    _write_tone(audio_path, 0.05, channels=1)

    report = build_master_delivery_qc(audio_path, knowledge_root=KNOWLEDGE_ROOT)
    stereo = next(check for check in report["checks"] if check["id"] == "format.stereo")

    assert stereo["status"] == "warning"
    assert report["overall_status"] == "review"


def test_qc_identity_changes_with_audio(tmp_path: Path) -> None:
    first_path = tmp_path / "first.wav"
    second_path = tmp_path / "second.wav"
    _write_tone(first_path, 0.05)
    _write_tone(second_path, 0.10)

    first = build_master_delivery_qc(first_path, knowledge_root=KNOWLEDGE_ROOT)
    second = build_master_delivery_qc(second_path, knowledge_root=KNOWLEDGE_ROOT)

    assert first["report_id"] != second["report_id"]


def _file_report(path: str = "C:/renders/master.wav") -> dict:
    return {
        "kind": "pampapilot_master_delivery_qc",
        "report_id": "a" * 24,
        "overall_status": "technical_checks_passed",
        "source": {"file_path": path},
        "measurements": {"channels": 2, "sample_rate_hz": 48_000},
        "checks": [],
    }


def _render_state() -> dict:
    return {
        "project_ref": "project:test",
        "project_state_change_count": 12,
        "project_dirty": False,
        "project_sample_rate_enabled": True,
        "project_sample_rate_hz": 48_000,
        "render_sample_rate_hz": 0,
        "render_channels": 2,
        "render_targets": "C:/renders/master.wav",
        "render_settings_flags": 0,
        "render_directory": "C:/renders",
        "render_pattern": "master",
        "render_dither_flags": 1,
        "render_normalize_flags": 0,
        "master_fx": [],
    }


def test_project_linkage_reports_consistent_configuration_without_claiming_provenance() -> None:
    report = build_project_master_delivery_qc(_render_state(), _file_report())

    assert report["render"]["mode"] == "master_mix"
    assert report["provenance"]["configuration_consistent"] is True
    assert report["provenance"]["render_provenance_verified"] is False
    assert report["verification"] == {
        "state_verified": True,
        "signal_verified": True,
        "perceptually_evaluated": False,
    }


def test_project_linkage_warns_for_dirty_project_and_mismatched_file() -> None:
    state = _render_state()
    state["project_dirty"] = True
    state["render_channels"] = 1
    state["render_sample_rate_hz"] = 44_100
    state["render_normalize_flags"] = 1
    state["master_fx"] = [{"name": "Limiter", "offline": True}]

    report = build_project_master_delivery_qc(
        state, _file_report("C:/elsewhere/other.wav")
    )
    statuses = {check["id"]: check["status"] for check in report["linkage_checks"]}

    assert report["overall_status"] == "review"
    assert statuses["render.channels_match_file"] == "warning"
    assert statuses["render.sample_rate_matches_file"] == "warning"
    assert statuses["render.target_matches_file"] == "warning"
    assert statuses["project.saved_state"] == "warning"
    assert statuses["render.normalization"] == "warning"
    assert statuses["master.fx_online"] == "warning"
