from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from pampapilot.producer_chain import (
    build_producer_chain_application_payload,
    build_track_producer_chain,
)


def _write_guitar(path: Path) -> None:
    sample_rate = 48_000
    duration = 3.0
    frames = round(sample_rate * duration)
    time = np.arange(frames, dtype=np.float64) / sample_rate
    rng = np.random.default_rng(77)
    audio = rng.normal(0.0, 0.003, frames)
    burst = ((time >= 0.8) & (time < 2.0)).astype(np.float64)
    audio += burst * 0.18 * np.sin(2 * np.pi * 1_200.0 * time)
    sf.write(path, audio.astype(np.float32), sample_rate, subtype="FLOAT")


def test_suno_chain_selects_evidence_backed_resonance_only(tmp_path: Path) -> None:
    path = tmp_path / "guitar.wav"
    _write_guitar(path)

    chain = build_track_producer_chain(
        path,
        "guitar",
        "suno_stems",
        existing_fx=[{"guid": "{FIR}", "name": "VST: ReaFir (Cockos)"}],
    )

    assert chain["review_status"] == "user_approval_required"
    assert [step["processor"] for step in chain["steps"]] == [
        "dynamic_resonance"
    ]
    assert chain["steps"][0]["binding"] == "create_new"
    assert chain["existing_fx_preserved"][0]["guid"] == "{FIR}"


def test_organic_chain_orders_cleanup_before_dynamics(tmp_path: Path) -> None:
    path = tmp_path / "guitar.wav"
    _write_guitar(path)

    chain = build_track_producer_chain(path, "guitar", "organic_multitrack")
    processors = [step["processor"] for step in chain["steps"]]

    assert processors.index("reaeq") < processors.index("dynamic_resonance")
    assert processors.index("dynamic_resonance") < processors.index("reacomp")
    assert processors == sorted(processors, key={
        "reagate": 10,
        "reaeq": 20,
        "dynamic_resonance": 30,
        "reacomp": 40,
        "deesser": 50,
        "waveshaper": 60,
    }.get)


def test_unknown_source_does_not_receive_a_chain(tmp_path: Path) -> None:
    path = tmp_path / "unknown.wav"
    _write_guitar(path)

    chain = build_track_producer_chain(path, "guitar", "unknown")

    assert chain["review_status"] == "no_processing_recommended"
    assert chain["steps"] == []


def test_existing_reaxcomp_blocks_ambiguous_reuse(tmp_path: Path) -> None:
    path = tmp_path / "guitar.wav"
    _write_guitar(path)

    chain = build_track_producer_chain(
        path,
        "guitar",
        "suno_stems",
        existing_fx=[{"guid": "{X}", "name": "VST: ReaXcomp (Cockos)"}],
    )

    assert chain["review_status"] == "blocked_existing_fx"
    assert chain["conflicts"][0]["kind"] == "ambiguous_existing_reaxcomp"


def test_approved_chain_builds_one_transaction_payload(tmp_path: Path) -> None:
    path = tmp_path / "guitar.wav"
    _write_guitar(path)
    chain = build_track_producer_chain(path, "guitar", "suno_stems")

    payload = build_producer_chain_application_payload(chain, chain["chain_id"])

    assert payload["chain_id"] == chain["chain_id"]
    assert len(payload["source_sha256"]) == 64
    assert payload["steps"][0]["processor"] == "dynamic_resonance"
    assert payload["steps"][0]["mode"] == "create_new"

    with pytest.raises(ValueError, match="does not match"):
        build_producer_chain_application_payload(chain, "0" * 24)
