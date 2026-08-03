import unittest

from pampapilot.web_actions import (
    capability_catalog,
    match_reaper_track,
    normalize_track_name,
)


class WebActionsTests(unittest.TestCase):
    def test_track_names_ignore_export_prefixes_and_accents(self):
        self.assertEqual(normalize_track_name("10 Vocals"), "vocals")
        self.assertEqual(normalize_track_name("3 Guitár.wav"), "guitarwav")

    def test_track_match_requires_a_unique_candidate(self):
        tracks = [
            {"guid": "{VOCAL}", "name": "Vocals"},
            {"guid": "{GUITAR}", "name": "Guitar"},
        ]
        self.assertEqual(
            match_reaper_track(tracks, "10 Vocals", "Vocals")["guid"],
            "{VOCAL}",
        )
        self.assertIsNone(
            match_reaper_track(
                [{"guid": "{A}", "name": "Drums"}, {"guid": "{B}", "name": "Drums"}],
                "5 Drums",
            )
        )

    def test_catalog_distinguishes_web_and_engine_capabilities(self):
        items = [item for group in capability_catalog() for item in group["items"]]
        statuses = {item["id"]: item["status"] for item in items}
        self.assertEqual(statuses["static_mix"], "web_ready")
        self.assertEqual(statuses["compression"], "web_ready")
        self.assertEqual(statuses["ambience"], "chat_ready")
        self.assertEqual(statuses["midi_cleanup"], "chat_ready")


if __name__ == "__main__":
    unittest.main()
