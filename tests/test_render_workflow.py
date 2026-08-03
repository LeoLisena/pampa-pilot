from __future__ import annotations

import pytest

from pampapilot.render_workflow import build_rendered_master_candidate_report


def _render_state() -> dict:
    return {
        "project_ref": "project:test",
        "project_state_change_count": 18,
        "project_dirty": True,
        "project_sample_rate_enabled": False,
        "project_sample_rate_hz": 0,
        "render_sample_rate_hz": 48_000,
        "render_channels": 2,
        "render_targets": "C:/sessions/song/candidate.wav",
        "render_settings_flags": 0,
        "render_directory": "C:/sessions/song",
        "render_pattern": "candidate",
        "render_dither_flags": 0,
        "render_normalize_flags": 0,
        "master_fx": [{"name": "VST: ReaLimit (Cockos)", "offline": False}],
    }


def _file_report(path: str = "C:/sessions/song/candidate.wav") -> dict:
    return {
        "kind": "pampapilot_master_delivery_qc",
        "report_id": "a" * 24,
        "overall_status": "technical_checks_passed",
        "source": {"file_path": path, "sha256": "b" * 64},
        "measurements": {"channels": 2, "sample_rate_hz": 48_000},
        "checks": [],
    }


def _bridge_reply() -> dict:
    request_id = "render-request"
    return {
        "request_id": request_id,
        "observations": {"state_verified": True},
        "result": {
            "transaction_request_id": request_id,
            "project_ref": "project:test",
            "project_path": "C:/sessions/song/song.rpp",
            "output_file": "C:/sessions/song/candidate.wav",
            "output_size_bytes": 123_456,
            "render_started_at_unix": 10,
            "render_completed_at_unix": 12,
            "render_action_id": 42230,
            "render_action_text": "Render project",
            "transport_was_stopped": True,
            "render_stats": "stats",
            "render_stats_summary": "summary",
            "render_settings": _render_state(),
        },
    }


def test_bridge_controlled_render_claims_provenance_after_hashing() -> None:
    report = build_rendered_master_candidate_report(
        _bridge_reply(), _file_report()
    )

    assert report["kind"] == "pampapilot_rendered_master_candidate"
    assert report["provenance"]["render_provenance_verified"] is True
    assert report["provenance"]["output_hash_verified_after_render"] is True
    assert report["render_receipt"]["output_sha256"] == "b" * 64
    assert report["render_receipt"]["transport_was_stopped"] is True
    assert report["verification"] == {
        "state_verified": True,
        "signal_verified": True,
        "perceptually_evaluated": False,
    }


def test_receipt_rejects_a_different_measured_file() -> None:
    with pytest.raises(ValueError, match="not the bridge-rendered"):
        build_rendered_master_candidate_report(
            _bridge_reply(), _file_report("C:/sessions/song/other.wav")
        )


def test_receipt_rejects_unverified_or_mismatched_transaction() -> None:
    reply = _bridge_reply()
    reply["observations"]["state_verified"] = False
    with pytest.raises(ValueError, match="did not verify"):
        build_rendered_master_candidate_report(reply, _file_report())

    reply = _bridge_reply()
    reply["result"]["transaction_request_id"] = "different"
    with pytest.raises(ValueError, match="identity"):
        build_rendered_master_candidate_report(reply, _file_report())
