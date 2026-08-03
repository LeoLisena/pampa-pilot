from __future__ import annotations

from pathlib import Path

import mido
import pytest

from pampapilot.midi_cleanup import MidiNote, write_midi
from pampapilot.midi_import import build_midi_import_payload


def test_builds_loss_aware_note_payload(tmp_path: Path) -> None:
    midi_path = tmp_path / "part.mid"
    write_midi(
        midi_path,
        [MidiNote(0, 480, 60, 90), MidiNote(480, 960, 64, 80)],
        ticks_per_beat=480,
        bpm=85.0,
        track_name="Part",
        program=24,
    )

    payload = build_midi_import_payload(
        midi_path, "MIDI Part", expected_bpm=85.0
    )

    assert payload["note_count"] == 2
    assert payload["end_tick"] == 960
    assert payload["ticks_per_beat"] == 480
    assert payload["muted"] is True
    assert payload["notes"][1]["pitch"] == 64
    assert payload["program_changes"] == [{"tick": 0, "channel": 0, "program": 24}]
    assert len(payload["source_sha256"]) == 64


def test_rejects_channel_events_that_would_be_lost(tmp_path: Path) -> None:
    midi_path = tmp_path / "controller.mid"
    midi = mido.MidiFile(type=1, ticks_per_beat=480)
    track = mido.MidiTrack()
    track.append(mido.Message("control_change", control=64, value=127, time=0))
    track.append(mido.Message("note_on", note=60, velocity=90, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, time=480))
    midi.tracks.append(track)
    midi.save(midi_path)

    with pytest.raises(ValueError, match="unsupported channel events: control_change"):
        build_midi_import_payload(midi_path, "Part")
