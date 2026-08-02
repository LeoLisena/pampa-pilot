from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from pampapilot.midi_cleanup import (
    CleanupConfig,
    MidiNote,
    ParsedMidi,
    _has_pitch_collision,
    _octave_candidate,
    output_tempo_events,
    parse_midi,
    safe_cleanup,
    write_midi,
)


class MidiCleanupTests(unittest.TestCase):
    def test_safe_cleanup_removes_duplicates_and_short_overlap(self) -> None:
        parsed = ParsedMidi(
            ticks_per_beat=480,
            notes=(
                MidiNote(0, 121, 60, 80, source_index=0),
                MidiNote(120, 240, 60, 81, source_index=1),
                MidiNote(300, 420, 64, 82, source_index=2),
                MidiNote(300, 420, 64, 82, source_index=3),
            ),
            tempo_events=((0, 500_000), (480, 705_882)),
            track_name="Test",
            program=24,
            unmatched_note_offs=0,
            hanging_note_ons=0,
        )

        notes, changes = safe_cleanup(parsed, target_bpm=85.0)

        self.assertEqual(len(notes), 3)
        self.assertEqual(notes[0].end_tick, 120)
        kinds = {change["kind"] for change in changes}
        self.assertIn("remove_exact_duplicate", kinds)
        self.assertIn("trim_short_overlap", kinds)
        self.assertIn("replace_tempo_map", kinds)

    def test_safe_cleanup_preserves_tempo_without_explicit_target(self) -> None:
        parsed = ParsedMidi(480, (), ((0, 500_000), (480, 600_000)), "Test", 0, 0, 0)
        _, changes = safe_cleanup(parsed)
        self.assertNotIn("replace_tempo_map", {change["kind"] for change in changes})
        self.assertEqual(output_tempo_events(parsed, None), parsed.tempo_events)

    def test_octave_candidate_uses_configured_range(self) -> None:
        self.assertEqual(_octave_candidate(34, 40, 88), 46)
        self.assertEqual(_octave_candidate(96, 40, 88), 84)
        self.assertIsNone(_octave_candidate(64, 40, 88))

    def test_pitch_correction_detects_existing_note_collision(self) -> None:
        original = MidiNote(0, 240, 34, 80, source_index=0)
        chord_note = MidiNote(0, 240, 46, 80, source_index=1)
        self.assertTrue(_has_pitch_collision(original, 46, [original, chord_note]))

    def test_default_config_is_song_and_instrument_neutral(self) -> None:
        config = CleanupConfig()
        self.assertIsNone(config.bpm)
        self.assertEqual(config.profile, "generic")
        self.assertIsNone(config.minimum_pitch)
        self.assertIsNone(config.maximum_pitch)
        self.assertFalse(config.enable_quantization)

    def test_written_midi_round_trips_without_structural_errors(self) -> None:
        notes = [MidiNote(0, 120, 60, 80), MidiNote(120, 360, 64, 90)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roundtrip.mid"
            write_midi(
                path,
                notes,
                ticks_per_beat=480,
                bpm=85.0,
                time_signature=(3, 4),
                track_name="Instrument",
                program=24,
            )
            parsed = parse_midi(path)

        observed = [
            (n.start_tick, n.end_tick, n.pitch, n.velocity, n.channel) for n in parsed.notes
        ]
        expected = [
            (n.start_tick, n.end_tick, n.pitch, n.velocity, n.channel) for n in notes
        ]
        self.assertEqual(observed, expected)
        self.assertEqual(len(parsed.tempo_events), 1)
        self.assertEqual(parsed.time_signature, (3, 4))
        self.assertEqual(parsed.unmatched_note_offs, 0)
        self.assertEqual(parsed.hanging_note_ons, 0)


if __name__ == "__main__":
    unittest.main()
