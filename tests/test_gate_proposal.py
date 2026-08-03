from __future__ import annotations

from pathlib import Path

import pytest

from pampapilot.gate_proposal import (
    build_reagate_application_payload,
    build_reagate_proposal,
)


KNOWLEDGE_ROOT = Path(__file__).resolve().parents[1] / "knowledge"


def _metrics() -> dict[str, object]:
    return {
        "file_name": "organic-vocal.wav",
        "file_path": "C:/session/organic-vocal.wav",
        "sha256": "b" * 64,
        "quiet_block_ratio_below_minus_40_dbfs": 0.25,
        "quiet_rms_dbfs_p90_below_minus_40": -55.0,
        "active_rms_dbfs_p90": -18.0,
    }


def test_organic_vocal_gets_conservative_audition_proposal() -> None:
    proposal = build_reagate_proposal(
        _metrics(), "lead_vocal", "organic_multitrack", knowledge_root=KNOWLEDGE_ROOT
    )

    assert proposal["execute"] is False
    assert proposal["decision"] == "audition_only"
    assert proposal["processor"]["parameters"]["threshold_db"] == -42.0
    assert proposal["processor"]["parameters"]["hysteresis_db"] == -3.0
    assert proposal["observations"]["observed_quiet_to_active_gap_db"] == 37.0
    assert len(proposal["proposal_id"]) == 24


def test_suno_stem_is_not_recommended_even_with_quiet_passages() -> None:
    proposal = build_reagate_proposal(
        _metrics(), "lead_vocal", "suno_stems", knowledge_root=KNOWLEDGE_ROOT
    )

    assert proposal["decision"] == "not_recommended"
    assert proposal["processor"] is None


def test_insufficient_separation_does_not_invent_parameters() -> None:
    metrics = _metrics()
    metrics["active_rms_dbfs_p90"] = -48.0

    proposal = build_reagate_proposal(
        metrics, "guitar", "organic_multitrack", knowledge_root=KNOWLEDGE_ROOT
    )

    assert proposal["decision"] == "insufficient_evidence"
    assert proposal["processor"] is None


def test_same_gate_evidence_has_stable_identity() -> None:
    first = build_reagate_proposal(
        _metrics(), "lead_vocal", "organic_multitrack", knowledge_root=KNOWLEDGE_ROOT
    )
    second = build_reagate_proposal(
        _metrics(), "lead_vocal", "organic_multitrack", knowledge_root=KNOWLEDGE_ROOT
    )

    assert first["proposal_id"] == second["proposal_id"]


def test_approved_gate_proposal_can_create_or_reuse_exact_fx() -> None:
    proposal = build_reagate_proposal(
        _metrics(), "lead_vocal", "organic_multitrack", knowledge_root=KNOWLEDGE_ROOT
    )

    create = build_reagate_application_payload(
        proposal, proposal["proposal_id"], None
    )
    reuse = build_reagate_application_payload(
        proposal, proposal["proposal_id"], "{GATE-GUID}"
    )

    assert create["mode"] == "create_new"
    assert create["parameters"]["threshold_db"] == -42.0
    assert reuse["mode"] == "reuse_existing"
    assert reuse["fx_guid"] == "{GATE-GUID}"


def test_stale_or_rejected_gate_proposal_cannot_be_applied() -> None:
    proposal = build_reagate_proposal(
        _metrics(), "lead_vocal", "organic_multitrack", knowledge_root=KNOWLEDGE_ROOT
    )
    with pytest.raises(ValueError, match="does not match"):
        build_reagate_application_payload(proposal, "0" * 24, None)

    suno = build_reagate_proposal(
        _metrics(), "lead_vocal", "suno_stems", knowledge_root=KNOWLEDGE_ROOT
    )
    with pytest.raises(ValueError, match="audition-only"):
        build_reagate_application_payload(suno, suno["proposal_id"], None)
