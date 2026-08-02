from __future__ import annotations

import unittest

from pampapilot.actions import ACTION_SPECS, VerificationLevel, require_action


class ActionCatalogTests(unittest.TestCase):
    def test_first_mvp_has_small_explicit_allowlist(self) -> None:
        self.assertEqual(len(ACTION_SPECS), 16)
        self.assertFalse(require_action("health_check").mutates_project)
        self.assertTrue(require_action("set_track_pan").mutates_project)
        self.assertTrue(require_action("set_track_volume").mutates_project)
        self.assertTrue(require_action("set_track_mute").mutates_project)
        self.assertTrue(require_action("apply_track_mix_batch").mutates_project)
        self.assertTrue(require_action("configure_reaeq_band").mutates_project)
        self.assertEqual(
            require_action("set_track_pan").minimum_verification,
            VerificationLevel.STATE,
        )
        self.assertTrue(require_action("import_audio").mutates_project)
        self.assertTrue(require_action("import_audio_batch").mutates_project)
        self.assertEqual(
            require_action("set_project_tempo").minimum_verification,
            VerificationLevel.STATE,
        )
        self.assertTrue(require_action("save_project_as").mutates_project)

    def test_arbitrary_action_is_rejected(self) -> None:
        with self.assertRaisesRegex(LookupError, "acción no permitida"):
            require_action("execute_lua")


if __name__ == "__main__":
    unittest.main()
