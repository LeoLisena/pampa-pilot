from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from pampapilot.vocal_rider import build_vocal_rider_proposal


def _write_phrases(path: Path) -> None:
    sample_rate = 48_000
    sections = [
        np.zeros(round(0.30 * sample_rate)),
        np.full(round(0.50 * sample_rate), 0.05),
        np.zeros(round(0.35 * sample_rate)),
        np.full(round(0.50 * sample_rate), 0.20),
        np.zeros(round(0.30 * sample_rate)),
    ]
    sf.write(path, np.concatenate(sections), sample_rate, subtype="FLOAT")


def test_organic_profile_detects_phrases_and_limits_corrections(tmp_path: Path) -> None:
    audio = tmp_path / "vocal.wav"
    _write_phrases(audio)

    proposal = build_vocal_rider_proposal(audio, "organic_multitrack")

    assert proposal["status"] == "audition_only"
    assert proposal["phrase_count"] == 2
    corrections = [phrase["correction_db"] for phrase in proposal["phrases"]]
    assert corrections[0] > 0
    assert corrections[1] < 0
    assert max(abs(value) for value in corrections) <= 3.0
    assert len(proposal["envelope_points"]) == 8
    assert proposal["time_reference"] == "source_file_start"
    assert -45.0 <= proposal["activity_threshold_dbfs"] <= -30.0


def test_suno_profile_does_not_emit_ambiguous_internal_riding(tmp_path: Path) -> None:
    audio = tmp_path / "vocal.wav"
    _write_phrases(audio)
    suno = build_vocal_rider_proposal(audio, "suno_stems")
    assert suno["status"] == "not_recommended"
    assert suno["envelope_points"] == []
    assert all(p["correction_db"] == 0.0 for p in suno["phrases"])
    assert suno["proposal_id"] == build_vocal_rider_proposal(
        audio, "suno_stems"
    )["proposal_id"]


def test_rejects_invalid_source_kind(tmp_path: Path) -> None:
    audio = tmp_path / "vocal.wav"
    _write_phrases(audio)
    with pytest.raises(ValueError, match="unsupported source kind"):
        build_vocal_rider_proposal(audio, "other")  # type: ignore[arg-type]
