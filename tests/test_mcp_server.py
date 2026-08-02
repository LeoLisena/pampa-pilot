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
                "get_track_state",
                "create_track",
                "set_track_pan",
                "set_track_volume",
                "set_track_mute",
                "apply_track_mix_batch",
                "add_stock_fx",
                "configure_reacomp",
                "configure_reaeq_band",
                "import_audio",
                "import_audio_batch",
                "set_project_tempo",
                "save_project_as",
                "undo_transaction",
            },
        )
        tools = {tool.name: tool for tool in result.tools}
        self.assertTrue(tools["health_check"].annotations.read_only_hint)
        self.assertTrue(tools["get_project_state"].annotations.read_only_hint)
        self.assertFalse(tools["create_track"].annotations.read_only_hint)
        self.assertFalse(tools["create_track"].annotations.destructive_hint)
        self.assertTrue(tools["set_track_pan"].annotations.idempotent_hint)
        self.assertTrue(tools["set_track_volume"].annotations.idempotent_hint)
        self.assertTrue(tools["set_track_mute"].annotations.idempotent_hint)
        self.assertTrue(tools["apply_track_mix_batch"].annotations.idempotent_hint)
        self.assertFalse(tools["add_stock_fx"].annotations.idempotent_hint)
        self.assertFalse(tools["add_stock_fx"].annotations.destructive_hint)
        self.assertTrue(tools["configure_reacomp"].annotations.idempotent_hint)
        self.assertFalse(tools["configure_reacomp"].annotations.destructive_hint)
        self.assertTrue(tools["configure_reaeq_band"].annotations.idempotent_hint)
        self.assertFalse(tools["configure_reaeq_band"].annotations.destructive_hint)
        self.assertFalse(tools["import_audio"].annotations.destructive_hint)
        self.assertFalse(tools["import_audio"].annotations.idempotent_hint)
        self.assertFalse(tools["import_audio_batch"].annotations.idempotent_hint)
        self.assertTrue(tools["set_project_tempo"].annotations.idempotent_hint)
        self.assertFalse(tools["save_project_as"].annotations.destructive_hint)
        self.assertTrue(tools["save_project_as"].annotations.idempotent_hint)
        self.assertTrue(tools["undo_transaction"].annotations.destructive_hint)


if __name__ == "__main__":
    unittest.main()
