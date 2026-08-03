"""Translate a MIDI file into the strict note payload accepted by REAPER."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .midi_cleanup import inferred_bpm, parse_midi


MAX_IMPORT_NOTES = 8_000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_midi_import_payload(
    midi_path: Path,
    track_name: str,
    *,
    position_quarter_notes: float = 0.0,
    muted: bool = True,
    expected_bpm: float | None = None,
) -> dict[str, Any]:
    """Build a loss-aware payload; reject events the bridge cannot preserve yet."""
    midi_path = Path(midi_path)
    if not midi_path.is_file():
        raise FileNotFoundError(midi_path)
    if not track_name or len(track_name) > 128:
        raise ValueError("track_name must contain 1 to 128 characters")
    if not 0.0 <= position_quarter_notes <= 1_000_000.0:
        raise ValueError("position_quarter_notes is outside the supported range")

    parsed = parse_midi(midi_path)
    if not parsed.notes:
        raise ValueError("the MIDI contains no complete notes")
    if len(parsed.notes) > MAX_IMPORT_NOTES:
        raise ValueError(f"the MIDI exceeds the {MAX_IMPORT_NOTES}-note import limit")
    if parsed.unmatched_note_offs or parsed.hanging_note_ons:
        raise ValueError("the MIDI has unmatched or hanging note events")
    if parsed.passthrough_events:
        event_types = sorted({message.type for _, message in parsed.passthrough_events})
        raise ValueError(
            "the MIDI contains unsupported channel events: " + ", ".join(event_types)
        )
    if parsed.ignored_meta_event_count:
        raise ValueError(
            "the MIDI contains unsupported meta events; clean or explicitly preserve them first"
        )

    bpm = inferred_bpm(parsed) if expected_bpm is None else expected_bpm
    if not 20.0 <= bpm <= 400.0:
        raise ValueError("expected_bpm must be between 20 and 400")
    notes = [
        {
            "start_tick": note.start_tick,
            "end_tick": note.end_tick,
            "pitch": note.pitch,
            "velocity": note.velocity,
            "channel": note.channel,
        }
        for note in parsed.notes
    ]
    program_changes = [
        {
            "tick": tick,
            "channel": message.channel,
            "program": message.program,
        }
        for tick, message in parsed.program_events
    ]
    return {
        "file_path": str(midi_path.resolve()),
        "source_sha256": _sha256(midi_path),
        "track_name": track_name,
        "position_quarter_notes": position_quarter_notes,
        "muted": muted,
        "expected_bpm": bpm,
        "ticks_per_beat": parsed.ticks_per_beat,
        "time_signature": list(parsed.time_signature),
        "note_count": len(notes),
        "end_tick": max(note["end_tick"] for note in notes),
        "notes": notes,
        "program_changes": program_changes,
    }
