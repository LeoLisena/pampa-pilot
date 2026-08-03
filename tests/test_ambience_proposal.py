from __future__ import annotations

from pathlib import Path

import pytest

from pampapilot.ambience_proposal import (
    build_ambience_application_payload,
    build_ambience_proposal,
)


KNOWLEDGE_ROOT = Path(__file__).resolve().parents[1] / "knowledge"


def _metrics() -> dict[str, object]:
    return {
        "file_name": "organic-vocal.wav",
        "file_path": "C:/session/organic-vocal.wav",
        "sha256": "d" * 64,
    }


def test_organic_vocal_gets_reverb_bus_audition() -> None:
    proposal = build_ambience_proposal(
        _metrics(), "lead_vocal", "reverb", 85.0, "organic_multitrack",
        knowledge_root=KNOWLEDGE_ROOT,
    )

    assert proposal["decision"] == "audition_only"
    assert proposal["processor"]["bus_name"] == "BUS Vocal Reverb"
    assert proposal["processor"]["send_db"] == -16.0
    assert proposal["processor"]["parameters"]["predelay_ms"] == 35.0


def test_delay_is_converted_from_beats_using_current_tempo() -> None:
    proposal = build_ambience_proposal(
        _metrics(), "lead_vocal", "delay", 85.0, "organic_multitrack",
        knowledge_root=KNOWLEDGE_ROOT,
    )

    assert proposal["processor"]["parameters"]["delay_ms"] == 352.9
    assert proposal["processor"]["parameters"]["feedback_db"] == -15.0


def test_suno_gets_subtle_profile_and_unknown_requires_confirmation() -> None:
    suno = build_ambience_proposal(
        _metrics(), "guitar", "reverb", 85.0, "suno_stems",
        knowledge_root=KNOWLEDGE_ROOT,
    )
    unknown = build_ambience_proposal(
        _metrics(), "guitar", "delay", 85.0, "unknown",
        knowledge_root=KNOWLEDGE_ROOT,
    )

    assert suno["decision"] == "audition_only"
    assert suno["processor"]["send_db"] == -26.0
    assert suno["processor"]["parameters"]["room_size"] == 30.0
    assert unknown["decision"] == "source_confirmation_required"
    assert unknown["processor"] is None


def test_approved_ambience_payload_is_bound_to_current_proposal() -> None:
    proposal = build_ambience_proposal(
        _metrics(), "lead_vocal", "reverb", 85.0, "organic_multitrack",
        knowledge_root=KNOWLEDGE_ROOT,
    )
    payload = build_ambience_application_payload(proposal, proposal["proposal_id"])

    assert payload["source_sha256"] == "d" * 64
    assert payload["effect_type"] == "reverb"
    with pytest.raises(ValueError, match="does not match"):
        build_ambience_application_payload(proposal, "0" * 24)
