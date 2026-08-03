from __future__ import annotations

from pampapilot.production_plan import build_production_plan


def _diagnosis() -> dict:
    return {
        "execute": False,
        "verification": {"signal_verified": True},
        "stems": [
            {
                "track_name": "Synth",
                "role": "synth",
                "source_kind": "suno_stems",
                "audio_identity": {"sha256": "a" * 64},
                "findings": [],
            },
            {
                "track_name": "Drums- OK 1",
                "role": "drums",
                "source_kind": "suno_stems",
                "audio_identity": {"sha256": "b" * 64},
                "findings": [],
            },
            {
                "track_name": "Drums 2",
                "role": "drums",
                "source_kind": "suno_stems",
                "audio_identity": {"sha256": "c" * 64},
                "findings": [],
            },
            {
                "track_name": "Vocals",
                "role": "lead_vocal",
                "source_kind": "organic_multitrack",
                "audio_identity": {"sha256": "d" * 64},
                "findings": [
                    {
                        "id": "stereo.negative_correlation",
                        "severity": "medium",
                        "confidence": "medium",
                        "observation": "Correlation is negative.",
                        "suggested_action": "Check mono.",
                    }
                ],
            },
        ],
        "relationships": {
            "exact_duplicate_groups": [],
            "spectral_overlap_candidates": [
                {
                    "tracks": ["Drums- OK 1", "Drums 2"],
                    "spectral_similarity": 0.99,
                    "priority_score": 0.8,
                    "confidence": "low_candidate_only",
                },
                {
                    "tracks": ["Synth", "Vocals"],
                    "spectral_similarity": 0.8,
                    "priority_score": 0.7,
                    "confidence": "low_candidate_only",
                },
            ],
        },
    }


def _track(name: str, guid: str, *, muted: bool = False, solo: int = 0, fx: int = 0) -> dict:
    return {
        "name": name,
        "guid": guid,
        "muted": muted,
        "solo": solo,
        "volume_db": -6.0,
        "pan": 0.0,
        "fx_count": fx,
    }


def _project() -> dict:
    return {
        "project_ref": "project:test",
        "project_path": "C:/session/test.rpp",
        "tempo_bpm": 85.0,
        "project_state_change_count": 7,
        "tracks": [
            _track("Synth", "{SYNTH}"),
            _track("Drums OK 1", "{D1}"),
            _track("Drums 2", "{D2}", muted=True),
            _track("Vocals", "{VOX}", fx=2),
            _track("Guitar MIDI - Safe", "{MIDI}", solo=2, fx=1),
        ],
    }


def test_plan_binds_normalized_names_and_uses_current_mute_state() -> None:
    plan = build_production_plan(
        _diagnosis(),
        _project(),
        {
            "{VOX}": {
                "fx": [
                    {
                        "guid": "{COMP}",
                        "name": "VST: ReaComp (Cockos)",
                        "enabled": True,
                        "offline": False,
                    }
                ]
            }
        },
    )

    assert plan["execute"] is False
    assert plan["summary"]["bound_stem_count"] == 4
    overlap = [
        item
        for item in plan["items"]
        if item["id"] == "relationship.spectral_overlap_candidate"
    ]
    assert {item["status"] for item in overlap} == {
        "resolved_in_current_mix",
        "review_required",
    }
    vocals = next(context for context in plan["track_contexts"] if context["track_name"] == "Vocals")
    assert vocals["fx"][0]["guid"] == "{COMP}"
    assert plan["verification"] == {
        "state_verified": True,
        "signal_verified": True,
        "perceptually_evaluated": False,
    }


def test_plan_flags_active_solo_and_unmanaged_track() -> None:
    plan = build_production_plan(_diagnosis(), _project())

    ids = [item["id"] for item in plan["items"]]
    assert "project.active_solo" in ids
    assert "project.unmanaged_track" in ids
    solo = next(item for item in plan["items"] if item["id"] == "project.active_solo")
    assert solo["priority"] == "high"
    assert solo["tracks"][0]["guid"] == "{MIDI}"


def test_plan_identity_changes_with_reaper_state() -> None:
    first = build_production_plan(_diagnosis(), _project())
    changed = _project()
    changed["project_state_change_count"] = 8
    second = build_production_plan(_diagnosis(), changed)

    assert first["plan_id"] != second["plan_id"]
