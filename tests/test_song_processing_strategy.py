from __future__ import annotations

from pathlib import Path

from pampapilot.song_processing_strategy import build_song_processing_strategy


KNOWLEDGE_ROOT = Path(__file__).resolve().parents[1] / "knowledge"


def _stem(
    name: str,
    role: str,
    source_kind: str,
    sha: str,
    finding_ids: list[str],
) -> dict:
    return {
        "track_name": name,
        "role": role,
        "source_kind": source_kind,
        "audio_identity": {"file_path": f"C:/media/{name}.wav", "sha256": sha},
        "observations": {
            "integrated_lufs": -18.0,
            "sample_peak_dbfs": -3.0,
            "crest_factor_db": 16.0,
            "active_rms_spread_db": 14.0,
            "stereo_correlation": 0.8,
        },
        "findings": [{"id": identifier} for identifier in finding_ids],
    }


def _diagnosis() -> dict:
    return {
        "execute": False,
        "song": {"name": "Hybrid", "bpm": 85.0},
        "knowledge": {"id": "test", "reviewed_at": "2026-08-02"},
        "verification": {"signal_verified": True},
        "stems": [
            _stem(
                "Vocals",
                "lead_vocal",
                "organic_multitrack",
                "a" * 64,
                [
                    "dynamics.wide_organic_performance",
                    "spectrum.vocal_low_frequency_candidate",
                ],
            ),
            _stem(
                "Synth",
                "synth",
                "suno_stems",
                "b" * 64,
                ["dynamics.already_controlled_suno"],
            ),
            _stem("Guitar", "guitar", "organic_multitrack", "c" * 64, []),
        ],
    }


def test_strategy_preserves_suno_and_selects_supported_organic_candidates() -> None:
    strategy = build_song_processing_strategy(
        _diagnosis(), knowledge_root=KNOWLEDGE_ROOT
    )
    items = {item["track_name"]: item for item in strategy["items"]}

    assert strategy["execute"] is False
    assert strategy["summary"]["audition_candidate_count"] == 1
    assert items["Synth"]["disposition"] == "preserve_existing_processing"
    assert items["Synth"]["chain"] == []
    assert items["Synth"]["problem_routes"][0]["next_stage"] == "leave_unchanged"
    assert items["Guitar"]["disposition"] == "no_observed_processing_trigger"
    assert [step["processor"] for step in items["Vocals"]["chain"]] == [
        "reaeq",
        "reacomp",
    ]
    assert strategy["verification"] == {
        "state_verified": False,
        "signal_verified": True,
        "perceptually_evaluated": False,
    }


def test_strategy_identity_changes_with_source_posture() -> None:
    first = build_song_processing_strategy(_diagnosis(), knowledge_root=KNOWLEDGE_ROOT)
    changed = _diagnosis()
    changed["stems"][0]["source_kind"] = "suno_stems"
    second = build_song_processing_strategy(changed, knowledge_root=KNOWLEDGE_ROOT)

    assert first["strategy_id"] != second["strategy_id"]
    assert second["summary"]["audition_candidate_count"] == 0


def test_unknown_source_blocks_source_dependent_processing() -> None:
    diagnosis = _diagnosis()
    diagnosis["stems"][0]["source_kind"] = "unknown"

    strategy = build_song_processing_strategy(diagnosis, knowledge_root=KNOWLEDGE_ROOT)
    vocals = strategy["items"][0]

    assert vocals["disposition"] == "classify_source_first"
    assert vocals["chain"] == []


def test_wide_organic_guitar_selects_compression_but_not_routine_eq() -> None:
    diagnosis = _diagnosis()
    guitar = diagnosis["stems"][2]
    guitar["findings"] = [{"id": "dynamics.wide_organic_performance"}]

    strategy = build_song_processing_strategy(diagnosis, knowledge_root=KNOWLEDGE_ROOT)
    guitar_item = strategy["items"][2]

    assert guitar_item["disposition"] == "audition_candidates"
    assert [step["processor"] for step in guitar_item["chain"]] == ["reacomp"]
