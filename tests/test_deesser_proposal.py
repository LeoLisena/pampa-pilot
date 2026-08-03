from __future__ import annotations

from pathlib import Path

import pytest

from pampapilot.deesser_proposal import (
    build_deesser_application_payload,
    build_deesser_proposal,
)


KNOWLEDGE_ROOT = Path(__file__).resolve().parents[1] / "knowledge"


def _metrics() -> dict[str, object]:
    return {
        "file_name": "organic-vocal.wav",
        "file_path": "C:/session/organic-vocal.wav",
        "sha256": "c" * 64,
        "sibilance_ratio_p95": 0.72,
        "sibilance_band_rms_dbfs_p50": -38.0,
        "sibilance_band_rms_dbfs_p90": -23.0,
        "sibilance_band_rms_dbfs_p95": -20.0,
        "sibilance_peak_to_median_db": 18.0,
    }


def test_organic_vocal_gets_band_limited_audition_proposal() -> None:
    proposal = build_deesser_proposal(
        _metrics(), "organic_multitrack", knowledge_root=KNOWLEDGE_ROOT
    )

    assert proposal["execute"] is False
    assert proposal["decision"] == "audition_only"
    assert proposal["processor"]["parameters"]["crossover_hz"] == 5200.0
    assert proposal["processor"]["parameters"]["threshold_db"] == -28.0
    assert proposal["processor"]["parameters"]["ratio"] == 3.0
    assert len(proposal["proposal_id"]) == 24


def test_suno_vocal_is_not_recommended_even_with_sibilant_peaks() -> None:
    proposal = build_deesser_proposal(
        _metrics(), "suno_stems", knowledge_root=KNOWLEDGE_ROOT
    )

    assert proposal["decision"] == "not_recommended"
    assert proposal["processor"] is None


def test_flat_high_frequency_content_is_not_called_sibilance() -> None:
    metrics = _metrics()
    metrics["sibilance_peak_to_median_db"] = 2.0

    proposal = build_deesser_proposal(
        metrics, "organic_multitrack", knowledge_root=KNOWLEDGE_ROOT
    )

    assert proposal["decision"] == "insufficient_evidence"
    assert proposal["processor"] is None


def test_approved_deesser_can_create_or_reuse_exact_fx() -> None:
    proposal = build_deesser_proposal(
        _metrics(), "organic_multitrack", knowledge_root=KNOWLEDGE_ROOT
    )

    create = build_deesser_application_payload(proposal, proposal["proposal_id"], None)
    reuse = build_deesser_application_payload(
        proposal, proposal["proposal_id"], "{XCOMP-GUID}"
    )

    assert create["mode"] == "create_new"
    assert create["parameters"]["threshold_db"] == -28.0
    assert reuse["mode"] == "reuse_existing"


def test_stale_or_rejected_deesser_cannot_be_applied() -> None:
    proposal = build_deesser_proposal(
        _metrics(), "organic_multitrack", knowledge_root=KNOWLEDGE_ROOT
    )
    with pytest.raises(ValueError, match="does not match"):
        build_deesser_application_payload(proposal, "0" * 24, None)

    suno = build_deesser_proposal(
        _metrics(), "suno_stems", knowledge_root=KNOWLEDGE_ROOT
    )
    with pytest.raises(ValueError, match="audition-only"):
        build_deesser_application_payload(suno, suno["proposal_id"], None)
