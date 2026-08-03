from __future__ import annotations

import pytest

from pampapilot.saturation_proposal import propose_saturation


def test_suno_profile_is_more_conservative_than_organic() -> None:
    suno = propose_saturation("suno_stems")
    organic = propose_saturation("organic_multitrack")

    assert suno["status"] == "audition_only"
    assert suno["parameters"]["drive_percent"] < organic["parameters"]["drive_percent"]
    assert suno["level_compensation"]["measured"] is False
    assert suno["fixed_controls"] == {
        "processing": "stereo",
        "waveshaper": "type_1",
        "limiter": False,
        "oversample_x2": True,
    }


def test_proposal_is_deterministic_and_rejects_unknown_values() -> None:
    assert (
        propose_saturation("unknown")["proposal_id"]
        == propose_saturation("unknown")["proposal_id"]
    )
    with pytest.raises(ValueError, match="unsupported source kind"):
        propose_saturation("other")  # type: ignore[arg-type]
