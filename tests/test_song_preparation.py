from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from pampapilot.midi_cleanup import MidiNote, write_midi
from pampapilot.song_preparation import (
    SongPreparationConfig,
    build_song_manifest,
    classify_stem,
    prepare_song,
)


def _write_wav(path: Path, duration: float = 1.0, value: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 8_000
    data = np.full((round(sample_rate * duration), 2), value, dtype=np.float32)
    sf.write(path, data, sample_rate, subtype="PCM_16")


def _workspace(tmp_path: Path) -> Path:
    stems = tmp_path / "media" / "inbox" / "stems" / "Song"
    midi = tmp_path / "media" / "inbox" / "midi" / "Song"
    reference = tmp_path / "media" / "references" / "Song.wav"
    _write_wav(stems / "0 Synth.wav")
    _write_wav(stems / "1 Guitar.wav", value=0.1)
    _write_wav(stems / "2 Drums.wav", value=0.2)
    _write_wav(stems / "3 Drums.wav", value=0.3)
    _write_wav(reference, value=0.2)
    midi.mkdir(parents=True)
    write_midi(
        midi / "1 Guitar.mid",
        [MidiNote(0, 480, 60, 90)],
        ticks_per_beat=480,
        bpm=85.0,
        track_name="Guitar",
    )
    return tmp_path


def test_classifies_common_stem_names() -> None:
    assert classify_stem(Path("9 Backing_Vocals.wav")) == "backing_vocals"
    assert classify_stem(Path("4 Bass.wav")) == "bass"
    assert classify_stem(Path("5 Drums.wav")) == "drums"
    assert classify_stem(Path("2 Keyboard.wav")) == "keys"
    assert classify_stem(Path("6 Cuerdas.wav")) == "strings"
    assert classify_stem(Path("7 Cello.wav")) == "strings"


def test_preview_builds_import_plan_without_writing(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    manifest = build_song_manifest(
        "Song", SongPreparationConfig(bpm=85.0), workspace_root=root
    )

    assert manifest["validation"]["status"] == "ready"
    assert manifest["summary"]["stem_count"] == 4
    assert manifest["summary"]["midi_count"] == 1
    assert manifest["midi"][0]["paired_audio_path"].endswith("1 Guitar.wav")
    assert manifest["reaper_import_plan"]["execute"] is False
    assert [stem["suggested_track_name"] for stem in manifest["stems"]][-2:] == [
        "Drums 1",
        "Drums 2",
    ]
    assert manifest["outputs_written"] is False
    assert not Path(manifest["paths"]["manifest"]).exists()


def test_prepare_song_writes_deterministic_manifest_under_sessions(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    config = SongPreparationConfig(bpm=85.0)

    first = prepare_song("Song", config, workspace_root=root)
    path = Path(first["paths"]["manifest"])
    first_bytes = path.read_bytes()
    second = prepare_song("Song", config, workspace_root=root)

    assert first["outputs_written"] is True
    assert second["outputs_written"] is True
    assert path.is_relative_to(root / "sessions")
    assert path.read_bytes() == first_bytes
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["kind"] == "pampapilot_song_manifest"
