from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from pampapilot.agent_context import build_project_context
from pampapilot.project_analysis import (
    analyze_project_media,
    default_diagnosis_source,
    load_project_analysis,
    public_project_analysis,
    source_overrides_from_metadata,
)


KNOWLEDGE_ROOT = Path(__file__).resolve().parents[1] / "knowledge"


def _write_tone(path: Path) -> None:
    sample_rate = 48_000
    time = np.arange(sample_rate, dtype=np.float32) / sample_rate
    mono = 0.2 * np.sin(2 * np.pi * 440 * time)
    sf.write(path, np.column_stack((mono, mono)), sample_rate, subtype="FLOAT")


def test_project_analysis_is_persistent_private_and_invalidated_by_changed_audio(
    tmp_path: Path,
) -> None:
    stems = tmp_path / "media" / "inbox" / "stems" / "Song"
    stems.mkdir(parents=True)
    audio_path = stems / "01 Vocals.wav"
    _write_tone(audio_path)
    (stems / "session.json").write_text(
        json.dumps(
            {"title": "Song", "tempo_bpm": 85, "source_kind": "unknown"}
        ),
        encoding="utf-8",
    )

    artifact = analyze_project_media(
        "Song",
        85,
        "unknown",
        knowledge_root=KNOWLEDGE_ROOT,
        workspace_root=tmp_path,
    )
    loaded = load_project_analysis("Song", 85, "unknown", workspace_root=tmp_path)
    public = public_project_analysis(artifact)
    context = build_project_context("Song", workspace_root=tmp_path)

    assert loaded is not None
    assert public["stems"][0]["name"] == "01 Vocals"
    assert str(tmp_path) not in json.dumps(public)
    assert context["verification"]["signal_analyzed"] is True
    assert context["analysis"]["summary"]["stem_count"] == 1

    with audio_path.open("ab") as stream:
        stream.write(b"changed")
    assert load_project_analysis("Song", 85, "unknown", workspace_root=tmp_path) is None


def test_mixed_source_is_neutral_until_per_stem_origins_are_declared() -> None:
    assert default_diagnosis_source("mixed") == "unknown"
    assert source_overrides_from_metadata(
        {"stem_sources": {"Vocals": "organic_multitrack", "Synth": "suno_stems"}}
    ) == [
        {"track_name": "Synth", "source_kind": "suno_stems"},
        {"track_name": "Vocals", "source_kind": "organic_multitrack"},
    ]

