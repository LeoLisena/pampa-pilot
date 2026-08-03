from __future__ import annotations

import pytest

from pampapilot.section_volume import (
    build_section_volume_application_payload,
    build_section_volume_proposal,
)


REGIONS = [
    {"kind": "verse", "label": "Verse 1", "start_seconds": 0.0, "end_seconds": 10.0},
    {"kind": "pre_chorus", "label": "Pre-Chorus", "start_seconds": 10.0, "end_seconds": 15.0},
    {"kind": "chorus", "label": "Chorus", "start_seconds": 15.0, "end_seconds": 25.0},
]


def test_suno_section_moves_are_optional_small_and_ramped() -> None:
    proposal = build_section_volume_proposal(REGIONS, "drums", "suno_stems")

    assert proposal["status"] == "optional_audition"
    assert proposal["enabled_by_default"] is False
    assert max(abs(section["relative_gain_db"]) for section in proposal["sections"]) <= 0.5
    assert proposal["sections"][2]["relative_gain_db"] == 0.2
    assert proposal["envelope_points"][1]["project_time_seconds"] == 9.95
    assert proposal["envelope_points"][2]["project_time_seconds"] == 10.05
    assert proposal["envelope_points"][-1]["gain_db"] == 0.0
    assert proposal["proposal_id"] == build_section_volume_proposal(
        REGIONS, "drums", "suno_stems"
    )["proposal_id"]


def test_organic_profile_retains_stronger_but_limited_moves() -> None:
    proposal = build_section_volume_proposal(REGIONS, "backing_vocals", "organic_multitrack")
    assert proposal["sections"][2]["relative_gain_db"] == 0.5
    assert proposal["maximum_absolute_move_db"] == 0.75


def test_application_requires_exact_approved_preview() -> None:
    proposal = build_section_volume_proposal(REGIONS, "lead_vocal", "unknown")
    payload = build_section_volume_application_payload(proposal, proposal["proposal_id"])
    assert payload["proposal_id"] == proposal["proposal_id"]
    with pytest.raises(ValueError, match="does not match"):
        build_section_volume_application_payload(proposal, "0" * 24)


def test_rejects_gaps_between_regions() -> None:
    broken = [dict(region) for region in REGIONS]
    broken[1]["start_seconds"] = 10.5
    with pytest.raises(ValueError, match="contiguous"):
        build_section_volume_proposal(broken, "guitar", "suno_stems")
