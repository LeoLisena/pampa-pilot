from __future__ import annotations

import unittest

from mcp import Client

from pampapilot.mcp_server import mcp


class MCPServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_publishes_only_the_initial_tools(self) -> None:
        async with Client(mcp) as client:
            result = await client.list_tools()

        self.assertEqual(
            {tool.name for tool in result.tools},
            {
                "health_check",
                "get_project_state",
                "get_render_settings",
                "get_track_state",
                "create_track",
                "set_track_pan",
                "set_track_volume",
                "set_track_mute",
                "set_track_solo",
                "apply_listening_preparation",
                "apply_track_mix_batch",
                "add_stock_fx",
                "add_instrument",
                "configure_reacomp",
                "configure_reaeq_band",
                "import_audio",
                "import_audio_batch",
                "import_midi",
                "import_midi_batch",
                "set_project_tempo",
                "save_project_as",
                "undo_transaction",
                "discover_song_media",
                "analyze_midi",
                "preview_master_delivery_qc",
                "preview_project_master_delivery_qc",
                "propose_track_processing",
                "apply_processing_proposal",
                "diagnose_song",
                "preview_song_processing_strategy",
                "preview_production_plan",
                "preview_midi_cleanup",
                "clean_midi_files",
                "preview_song_preparation",
                "prepare_song",
            },
        )
        tools = {tool.name: tool for tool in result.tools}
        self.assertTrue(tools["health_check"].annotations.read_only_hint)
        self.assertTrue(tools["get_project_state"].annotations.read_only_hint)
        self.assertTrue(tools["get_render_settings"].annotations.read_only_hint)
        self.assertFalse(tools["create_track"].annotations.read_only_hint)
        self.assertFalse(tools["create_track"].annotations.destructive_hint)
        self.assertTrue(tools["set_track_pan"].annotations.idempotent_hint)
        self.assertTrue(tools["set_track_volume"].annotations.idempotent_hint)
        self.assertTrue(tools["set_track_mute"].annotations.idempotent_hint)
        self.assertTrue(tools["set_track_solo"].annotations.idempotent_hint)
        self.assertFalse(tools["apply_listening_preparation"].annotations.read_only_hint)
        self.assertFalse(tools["apply_listening_preparation"].annotations.idempotent_hint)
        self.assertFalse(tools["apply_listening_preparation"].annotations.destructive_hint)
        self.assertTrue(tools["apply_track_mix_batch"].annotations.idempotent_hint)
        self.assertFalse(tools["add_stock_fx"].annotations.idempotent_hint)
        self.assertFalse(tools["add_stock_fx"].annotations.destructive_hint)
        self.assertFalse(tools["add_instrument"].annotations.idempotent_hint)
        self.assertFalse(tools["add_instrument"].annotations.destructive_hint)
        self.assertTrue(tools["configure_reacomp"].annotations.idempotent_hint)
        self.assertFalse(tools["configure_reacomp"].annotations.destructive_hint)
        self.assertTrue(tools["configure_reaeq_band"].annotations.idempotent_hint)
        self.assertFalse(tools["configure_reaeq_band"].annotations.destructive_hint)
        self.assertFalse(tools["import_audio"].annotations.destructive_hint)
        self.assertFalse(tools["import_audio"].annotations.idempotent_hint)
        self.assertFalse(tools["import_audio_batch"].annotations.idempotent_hint)
        self.assertFalse(tools["import_midi"].annotations.idempotent_hint)
        self.assertFalse(tools["import_midi_batch"].annotations.idempotent_hint)
        self.assertFalse(tools["import_midi"].annotations.destructive_hint)
        self.assertTrue(tools["set_project_tempo"].annotations.idempotent_hint)
        self.assertFalse(tools["save_project_as"].annotations.destructive_hint)
        self.assertTrue(tools["save_project_as"].annotations.idempotent_hint)
        self.assertTrue(tools["undo_transaction"].annotations.destructive_hint)
        self.assertTrue(tools["discover_song_media"].annotations.read_only_hint)
        self.assertTrue(tools["analyze_midi"].annotations.read_only_hint)
        self.assertTrue(tools["preview_master_delivery_qc"].annotations.read_only_hint)
        self.assertTrue(tools["preview_project_master_delivery_qc"].annotations.read_only_hint)
        self.assertTrue(tools["propose_track_processing"].annotations.read_only_hint)
        self.assertFalse(tools["apply_processing_proposal"].annotations.read_only_hint)
        self.assertFalse(tools["apply_processing_proposal"].annotations.idempotent_hint)
        self.assertFalse(tools["apply_processing_proposal"].annotations.destructive_hint)
        self.assertTrue(tools["diagnose_song"].annotations.read_only_hint)
        self.assertTrue(tools["preview_song_processing_strategy"].annotations.read_only_hint)
        self.assertTrue(tools["preview_production_plan"].annotations.read_only_hint)
        self.assertTrue(tools["preview_midi_cleanup"].annotations.read_only_hint)
        self.assertFalse(tools["clean_midi_files"].annotations.read_only_hint)
        self.assertFalse(tools["clean_midi_files"].annotations.destructive_hint)
        self.assertTrue(tools["clean_midi_files"].annotations.idempotent_hint)
        self.assertTrue(tools["preview_song_preparation"].annotations.read_only_hint)
        self.assertFalse(tools["prepare_song"].annotations.read_only_hint)
        self.assertFalse(tools["prepare_song"].annotations.destructive_hint)
        self.assertTrue(tools["prepare_song"].annotations.idempotent_hint)


if __name__ == "__main__":
    unittest.main()
