from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from pampapilot.processing_proposal import (
    KnowledgeError,
    build_processing_application_payload,
    build_processing_proposal,
    propose_track_processing,
)


KNOWLEDGE_ROOT = Path(__file__).resolve().parents[1] / "knowledge"


def _metrics() -> dict[str, object]:
    return {
        "file_name": "10 Vocals.wav",
        "file_path": "C:/session/10 Vocals.wav",
        "sha256": "a" * 64,
        "integrated_lufs": -17.178,
        "sample_peak_dbfs": -3.045,
        "rms_dbfs": -22.869,
        "crest_factor_db": 19.824,
        "samples_at_or_above_0_dbfs": 0,
        "stereo_correlation": 0.911,
    }


def test_lead_vocal_proposal_is_non_executing_and_auditable() -> None:
    proposal = build_processing_proposal(
        _metrics(), "lead_vocal", "suno_stems", knowledge_root=KNOWLEDGE_ROOT
    )

    assert proposal["execute"] is False
    assert proposal["review_status"] == "user_approval_required"
    assert [step["processor"] for step in proposal["chain"]] == ["reaeq", "reacomp"]
    assert proposal["chain"][0]["parameters"] == {
        "band_type": "high_pass",
        "band_index": 0,
        "frequency_hz": 80.0,
        "gain_db": 0.0,
        "q": 0.71,
        "enabled": True,
    }
    compressor = proposal["chain"][1]
    assert compressor["parameters"]["threshold_db"] == -10.0
    assert compressor["parameters"]["ratio"] == 1.5
    assert compressor["evidence"]["theoretical_peak_reduction_ceiling_db"] == pytest.approx(
        2.318, abs=0.001
    )
    assert "Suno" in proposal["warnings"][0]
    assert len(proposal["proposal_id"]) == 24


def test_same_inputs_produce_same_proposal_identity() -> None:
    first = build_processing_proposal(
        _metrics(), "lead_vocal", knowledge_root=KNOWLEDGE_ROOT
    )
    second = build_processing_proposal(
        _metrics(), "lead_vocal", knowledge_root=KNOWLEDGE_ROOT
    )

    assert first["proposal_id"] == second["proposal_id"]


def test_bass_proposal_does_not_invent_an_eq_step() -> None:
    proposal = build_processing_proposal(
        _metrics(), "bass", knowledge_root=KNOWLEDGE_ROOT
    )

    assert [step["processor"] for step in proposal["chain"]] == ["reacomp"]
    assert proposal["chain"][0]["profile"] == "bass_control"


def test_missing_knowledge_is_rejected() -> None:
    with pytest.raises(KnowledgeError, match="does not exist"):
        build_processing_proposal(
            _metrics(), "lead_vocal", knowledge_root=Path("missing-knowledge")
        )


def test_audio_wrapper_does_not_write_files(tmp_path: Path) -> None:
    sample_rate = 48_000
    time = np.arange(sample_rate, dtype=np.float32) / sample_rate
    tone = 0.25 * np.sin(2.0 * np.pi * 220.0 * time)
    audio_path = tmp_path / "voice.wav"
    sf.write(audio_path, np.column_stack((tone, tone)), sample_rate, subtype="FLOAT")
    before = {path.resolve() for path in tmp_path.rglob("*")}

    proposal = propose_track_processing(
        audio_path, "lead_vocal", knowledge_root=KNOWLEDGE_ROOT
    )

    after = {path.resolve() for path in tmp_path.rglob("*")}
    assert proposal["execute"] is False
    assert after == before


def test_approved_proposal_binds_existing_and_new_fx() -> None:
    proposal = build_processing_proposal(
        _metrics(), "lead_vocal", knowledge_root=KNOWLEDGE_ROOT
    )

    payload = build_processing_application_payload(
        proposal,
        proposal["proposal_id"],
        [
            {"processor": "reaeq", "fx_guid": "{EQ-GUID}"},
            {"processor": "reacomp", "fx_guid": None},
        ],
    )

    assert payload["proposal_id"] == proposal["proposal_id"]
    assert payload["source_sha256"] == "a" * 64
    assert payload["steps"][0]["mode"] == "reuse_existing"
    assert payload["steps"][0]["fx_guid"] == "{EQ-GUID}"
    assert payload["steps"][1]["mode"] == "create_new"
    assert payload["steps"][1]["parameters"]["threshold_db"] == -10.0


def test_stale_or_incomplete_approval_is_rejected() -> None:
    proposal = build_processing_proposal(
        _metrics(), "lead_vocal", knowledge_root=KNOWLEDGE_ROOT
    )

    with pytest.raises(ValueError, match="does not match"):
        build_processing_application_payload(
            proposal,
            "0" * 24,
            [
                {"processor": "reaeq", "fx_guid": "{EQ-GUID}"},
                {"processor": "reacomp", "fx_guid": "{COMP-GUID}"},
            ],
        )
    with pytest.raises(ValueError, match="every proposed processor"):
        build_processing_application_payload(
            proposal,
            proposal["proposal_id"],
            [{"processor": "reacomp", "fx_guid": "{COMP-GUID}"}],
        )


def test_duplicate_processor_binding_is_rejected() -> None:
    proposal = build_processing_proposal(
        _metrics(), "lead_vocal", knowledge_root=KNOWLEDGE_ROOT
    )

    with pytest.raises(ValueError, match="duplicate processor binding"):
        build_processing_application_payload(
            proposal,
            proposal["proposal_id"],
            [
                {"processor": "reaeq", "fx_guid": "{EQ-1}"},
                {"processor": "reaeq", "fx_guid": "{EQ-2}"},
            ],
        )
