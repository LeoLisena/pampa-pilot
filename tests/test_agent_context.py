import json
from pathlib import Path
import tempfile
import unittest

from pampapilot.agent_context import (
    build_agent_messages,
    build_context_update_message,
    build_project_context,
    compact_project_context,
    lyric_sections,
    parse_agent_response,
    request_needs_deep_context,
)


class AgentContextTests(unittest.TestCase):
    def test_prefers_clean_lyrics_and_removes_paths_from_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stems = root / "media" / "inbox" / "stems" / "Canción"
            stems.mkdir(parents=True)
            (stems / "01 Voz.wav").write_bytes(b"RIFF")
            (stems / "lyric.txt").write_text("[Broken]\ntexto", encoding="utf-8")
            (stems / "lyric-clean.txt").write_text(
                "[Intro]\n\n[Verse 1]\nTexto", encoding="utf-8"
            )
            (stems / "session.json").write_text(
                json.dumps({"title": "Canción", "tempo_bpm": 85, "source_kind": "mixed"}),
                encoding="utf-8",
            )

            context = build_project_context("Canción", workspace_root=root)

            self.assertEqual(context["song"]["tempo_bpm"], 85)
            self.assertEqual(context["lyrics"]["sections"], ["Intro", "Verse 1"])
            self.assertEqual(context["stems"], [{"name": "01 Voz", "format": ".wav"}])
            self.assertNotIn(str(root), json.dumps(context))

    def test_sections_preserve_repeated_song_form(self):
        self.assertEqual(
            lyric_sections("[Verse]\na\n[Chorus]\nb\n[Verse]\nc"),
            ["Verse", "Chorus", "Verse"],
        )

    def test_agent_messages_include_structured_context_and_bounded_history(self):
        history = [{"role": "user", "content": str(index)} for index in range(12)]
        messages = build_agent_messages({"song": {"title": "Test"}}, "seguí", history)
        self.assertEqual(messages[-1], {"role": "user", "content": "seguí"})
        self.assertEqual(len(messages), 11)
        self.assertIn("Contexto estructurado", messages[1]["content"])

    def test_parses_structured_proposal_and_forces_approval(self):
        result = parse_agent_response(
            json.dumps(
                {
                    "message": "Propongo escuchar.",
                    "proposal": {
                        "title": "Voz",
                        "summary": "Control suave",
                        "risk": "low",
                        "requires_approval": False,
                        "changes": [
                            {"target": "Voz", "action": "A/B compresor", "reason": "Dinámica"}
                        ],
                    },
                }
            )
        )
        self.assertTrue(result["structured"])
        self.assertTrue(result["proposal"]["requires_approval"])

    def test_falls_back_to_text_without_creating_executable_proposal(self):
        result = parse_agent_response("Una respuesta no estructurada")
        self.assertFalse(result["structured"])
        self.assertIsNone(result["proposal"])

    def test_routes_greetings_to_compact_context_and_analysis_to_deep_context(self):
        self.assertFalse(request_needs_deep_context("hola, ¿cómo estás?"))
        self.assertTrue(request_needs_deep_context("analizá la mezcla y la voz"))
        compact = compact_project_context(
            {
                "song": {"title": "Test", "tempo_bpm": 85},
                "stems": [{"name": "Voz"}],
                "lyrics": {"sections": ["Verse"], "text": "secreto"},
                "verification": {"signal_analyzed": False},
            }
        )
        self.assertEqual(compact["stem_count"], 1)
        self.assertNotIn("lyrics", compact)

    def test_context_update_explicitly_preserves_same_project(self):
        message = build_context_update_message(
            {"song": {"title": "Test"}}, "analizá la voz"
        )
        self.assertIn("mismo proyecto", message)
        self.assertIn("analizá la voz", message)


if __name__ == "__main__":
    unittest.main()
