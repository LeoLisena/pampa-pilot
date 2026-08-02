from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from pampapilot.media_discovery import (
    MediaPathError,
    discover_song_media,
    resolve_input_file,
    resolve_output_directory,
)


class MediaDiscoveryTests(unittest.TestCase):
    def test_discovers_normalized_midi_stem_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stems = root / "media" / "inbox" / "stems" / "Song"
            midi = root / "media" / "inbox" / "midi" / "Song"
            references = root / "media" / "references"
            stems.mkdir(parents=True)
            midi.mkdir(parents=True)
            references.mkdir(parents=True)
            (stems / "3 Guitar.wav").touch()
            (midi / "3 Guitar (Guitar).mid").touch()
            (references / "Song.wav").touch()

            result = discover_song_media("song", workspace_root=root)

        self.assertEqual(result["complete_pair_count"], 1)
        self.assertEqual(len(result["references"]), 1)
        self.assertEqual(result["suggested_pairs"][0]["match_score"], 1.0)

    def test_input_and_output_paths_are_confined(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "media"
            sessions = root / "sessions"
            media.mkdir()
            sessions.mkdir()
            midi = media / "test.mid"
            midi.touch()

            self.assertEqual(resolve_input_file(midi, workspace_root=root), midi.resolve())
            self.assertEqual(
                resolve_output_directory(sessions / "Song", workspace_root=root),
                (sessions / "Song").resolve(),
            )
            with self.assertRaises(MediaPathError):
                resolve_input_file(root / "outside.mid", workspace_root=root)
            with self.assertRaises(MediaPathError):
                resolve_output_directory(media / "outputs", workspace_root=root)

    def test_song_name_cannot_be_a_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "not a path"):
                discover_song_media("../Song", workspace_root=Path(directory))


if __name__ == "__main__":
    unittest.main()
