from __future__ import annotations

from pathlib import Path

import pytest

from pampapilot.song_diagnosis import build_song_diagnosis


KNOWLEDGE_ROOT = Path(__file__).resolve().parents[1] / "knowledge"


def _audio(name: str, sha: str, *, spread: float, correlation: float = 0.5) -> dict:
    return {
        "file_name": f"{name}.wav",
        "file_path": f"C:/media/{name}.wav",
        "sha256": sha,
        "integrated_lufs": -20.0,
        "sample_peak_dbfs": -3.0,
        "crest_factor_db": 15.0,
        "active_rms_spread_db": spread,
        "stereo_correlation": correlation,
        "samples_at_or_above_0_dbfs": 0,
        "dc_offset": [0.0, 0.0],
        "sibilance_ratio_p95": 0.7,
        "low_frequency_ratio_below_100_hz_p95": 0.4,
        "near_silence_ratio_below_minus_60_dbfs": 0.1,
        "spectral_centroid_hz": 1_500.0,
        "spectral_band_energy_ratio": {
            "sub_bass_20_60": 0.05,
            "bass_60_250": 0.15,
            "low_mid_250_500": 0.15,
            "mid_500_2000": 0.35,
            "presence_2000_5000": 0.2,
            "sibilance_5000_10000": 0.08,
            "air_10000_20000": 0.02,
        },
    }


def _manifest() -> dict:
    return {
        "song": {"name": "Hybrid Song", "bpm": 85.0},
        "stems": [
            {
                "role": "synth",
                "suggested_track_name": "Synth",
                "audio": _audio("Synth", "a" * 64, spread=3.0),
            },
            {
                "role": "lead_vocal",
                "suggested_track_name": "Vocals",
                "audio": _audio("Vocals", "b" * 64, spread=14.0),
            },
            {
                "role": "guitar",
                "suggested_track_name": "Guitar",
                "audio": _audio("Guitar", "b" * 64, spread=13.0),
            },
        ],
    }


def test_hybrid_diagnosis_applies_source_policy_per_stem() -> None:
    result = build_song_diagnosis(
        _manifest(),
        "suno_stems",
        [
            {"track_name": "Vocals", "source_kind": "organic_multitrack"},
            {"track_name": "Guitar", "source_kind": "organic_multitrack"},
        ],
        knowledge_root=KNOWLEDGE_ROOT,
    )

    stems = {stem["track_name"]: stem for stem in result["stems"]}
    assert result["execute"] is False
    assert result["source_model"]["counts"] == {
        "suno_stems": 1,
        "organic_multitrack": 2,
    }
    assert stems["Synth"]["policy"]["posture"] == "preserve_existing_processing"
    assert stems["Vocals"]["policy"]["posture"] == "corrective_then_aesthetic"
    vocal_findings = {finding["id"] for finding in stems["Vocals"]["findings"]}
    assert "dynamics.wide_organic_performance" in vocal_findings
    assert "spectrum.vocal_low_frequency_candidate" in vocal_findings
    assert "spectrum.vocal_sibilance_candidate" in vocal_findings
    assert result["verification"]["signal_verified"] is True
    assert result["verification"]["perceptually_evaluated"] is False


def test_relationships_are_candidates_and_duplicates_are_exact() -> None:
    result = build_song_diagnosis(
        _manifest(), "suno_stems", knowledge_root=KNOWLEDGE_ROOT
    )

    assert result["relationships"]["exact_duplicate_groups"] == [["Vocals", "Guitar"]]
    assert result["relationships"]["spectral_overlap_candidates"]
    assert all(
        item["confidence"] == "low_candidate_only"
        for item in result["relationships"]["spectral_overlap_candidates"]
    )


def test_invalid_or_duplicate_override_is_rejected() -> None:
    with pytest.raises(ValueError, match="does not exist"):
        build_song_diagnosis(
            _manifest(),
            "suno_stems",
            [{"track_name": "Missing", "source_kind": "organic_multitrack"}],
            knowledge_root=KNOWLEDGE_ROOT,
        )
    with pytest.raises(ValueError, match="duplicate source override"):
        build_song_diagnosis(
            _manifest(),
            "suno_stems",
            [
                {"track_name": "Vocals", "source_kind": "organic_multitrack"},
                {"track_name": "Vocals", "source_kind": "suno_stems"},
            ],
            knowledge_root=KNOWLEDGE_ROOT,
        )
