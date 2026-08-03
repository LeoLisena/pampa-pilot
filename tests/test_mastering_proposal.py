from __future__ import annotations

from pathlib import Path

import pytest

from pampapilot.mastering_proposal import (
    build_mastering_application_payload,
    build_mastering_proposal,
)


KNOWLEDGE_ROOT = Path(__file__).resolve().parents[1] / "knowledge"


def _report(*, lufs: float = -14.4, true_peak: float = -0.18) -> dict:
    return {
        "kind": "pampapilot_master_delivery_qc",
        "report_id": "a" * 24,
        "source": {
            "file_path": "C:/media/master.wav",
            "sha256": "b" * 64,
        },
        "measurements": {
            "integrated_lufs": lufs,
            "estimated_true_peak_dbtp": true_peak,
        },
    }


def test_proposal_uses_safety_limiter_without_routine_loudness_gain() -> None:
    proposal = build_mastering_proposal(_report(), knowledge_root=KNOWLEDGE_ROOT)
    step = proposal["chain"][0]

    assert proposal["execute"] is False
    assert proposal["review_status"] == "user_approval_required"
    assert step["processor"] == "realimit"
    assert step["parameters"] == {
        "threshold_db": -1.5,
        "ceiling_db": -1.5,
        "release_ms": 50.0,
    }
    assert step["evidence"]["estimated_peak_reduction_required_db"] == pytest.approx(1.32)


def test_louder_master_uses_more_conservative_platform_ceiling() -> None:
    proposal = build_mastering_proposal(
        _report(lufs=-10.0, true_peak=-1.0), knowledge_root=KNOWLEDGE_ROOT
    )

    assert proposal["chain"][0]["parameters"]["ceiling_db"] == -2.5


def test_compliant_peak_does_not_propose_processing() -> None:
    proposal = build_mastering_proposal(
        _report(true_peak=-1.2), knowledge_root=KNOWLEDGE_ROOT
    )

    assert proposal["review_status"] == "no_action_recommended"
    assert proposal["chain"] == []


def test_approved_proposal_binds_optional_existing_fx() -> None:
    proposal = build_mastering_proposal(_report(), knowledge_root=KNOWLEDGE_ROOT)

    payload = build_mastering_application_payload(
        proposal, proposal["proposal_id"], "{LIMITER}"
    )

    assert payload["fx_guid"] == "{LIMITER}"
    assert payload["source_sha256"] == "b" * 64
    assert payload["parameters"]["release_ms"] == 50.0


def test_stale_or_empty_proposal_is_rejected() -> None:
    proposal = build_mastering_proposal(_report(), knowledge_root=KNOWLEDGE_ROOT)
    with pytest.raises(ValueError, match="does not match"):
        build_mastering_application_payload(proposal, "0" * 24, None)

    empty = build_mastering_proposal(
        _report(true_peak=-1.2), knowledge_root=KNOWLEDGE_ROOT
    )
    with pytest.raises(ValueError, match="no applicable"):
        build_mastering_application_payload(empty, empty["proposal_id"], None)
