from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from pampapilot.dynamic_resonance import (
    analyze_dynamic_resonance,
    build_dynamic_resonance_application_payload,
)


def _write_resonant_audio(path: Path) -> None:
    sample_rate = 48_000
    duration = 3.0
    frames = round(sample_rate * duration)
    time = np.arange(frames, dtype=np.float64) / sample_rate
    rng = np.random.default_rng(41)
    audio = rng.normal(0.0, 0.003, frames)
    burst = ((time >= 0.8) & (time < 2.0)).astype(np.float64)
    audio += burst * 0.18 * np.sin(2.0 * np.pi * 1_200.0 * time)
    sf.write(path, audio.astype(np.float32), sample_rate, subtype="FLOAT")


def test_organic_resonance_gets_one_broad_audition_band(tmp_path: Path) -> None:
    path = tmp_path / "guitar.wav"
    _write_resonant_audio(path)

    proposal = analyze_dynamic_resonance(path, "guitar", "organic_multitrack")

    assert proposal["decision"] == "audition_only"
    assert proposal["execute"] is False
    assert proposal["processor"]["target_band"] == 2
    parameters = proposal["processor"]["parameters"]
    assert parameters["lower_crossover_hz"] < 1_200 < parameters["upper_crossover_hz"]
    assert parameters["ratio"] == 1.6
    assert len(proposal["proposal_id"]) == 24


def test_suno_uses_more_conservative_dynamic_parameters(tmp_path: Path) -> None:
    path = tmp_path / "suno-guitar.wav"
    _write_resonant_audio(path)

    proposal = analyze_dynamic_resonance(path, "guitar", "suno_stems")

    assert proposal["decision"] == "audition_only"
    parameters = proposal["processor"]["parameters"]
    assert parameters["ratio"] == 1.25
    assert parameters["threshold_db"] > -45.0
    assert parameters["attack_ms"] == 20.0


def test_unknown_source_must_be_classified_even_with_evidence(tmp_path: Path) -> None:
    path = tmp_path / "unknown.wav"
    _write_resonant_audio(path)

    proposal = analyze_dynamic_resonance(path, "guitar", "unknown")

    assert proposal["decision"] == "classify_source_first"
    assert proposal["processor"] is None


def test_approved_proposal_can_create_or_reuse_exact_reaxcomp(tmp_path: Path) -> None:
    path = tmp_path / "guitar.wav"
    _write_resonant_audio(path)
    proposal = analyze_dynamic_resonance(path, "guitar", "organic_multitrack")

    create = build_dynamic_resonance_application_payload(
        proposal, proposal["proposal_id"], None
    )
    reuse = build_dynamic_resonance_application_payload(
        proposal, proposal["proposal_id"], "{REAXCOMP}"
    )

    assert create["mode"] == "create_new"
    assert reuse["mode"] == "reuse_existing"
    assert create["parameters"]["ratio"] == 1.6


def test_stale_proposal_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "guitar.wav"
    _write_resonant_audio(path)
    proposal = analyze_dynamic_resonance(path, "guitar", "organic_multitrack")

    with pytest.raises(ValueError, match="does not match"):
        build_dynamic_resonance_application_payload(proposal, "0" * 24, None)
