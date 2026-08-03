import unittest
from unittest.mock import patch
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from pampapilot.web_server import (
    _named_uploads,
    _ordered_stem_paths,
    _record_chat_exchange,
    _suggested_track_names,
    app,
    runtime,
)


class WebServerTests(unittest.TestCase):
    def setUp(self):
        self._chat_directory = TemporaryDirectory()
        self._chat_path_patch = patch(
            "pampapilot.web_server.CHAT_STATE_PATH",
            Path(self._chat_directory.name) / "web-chat-state.json",
        )
        self._chat_path_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self._chat_path_patch.stop()
        self._chat_directory.cleanup()

    def test_serves_application_shell(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("PampaPilot", response.text)
        self.assertIn("Productor IA", response.text)

    @patch("pampapilot.web_server._project_names", return_value=[])
    def test_project_list_returns_an_empty_collection(self, _names):
        response = self.client.get("/api/projects")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"projects": []})

    def test_public_settings_never_return_token(self):
        response = self.client.get("/api/settings/brain")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("token", response.json())
        self.assertTrue(response.json()["authentication_required"])
        self.assertEqual(response.json()["timeout_seconds"], 180.0)
        self.assertIn("token_persisted", response.json())

    def test_chat_state_is_shared_by_server(self):
        reasoning = self.client.put(
            "/api/chat/reasoning", json={"reasoning_mode": "deep"}
        )
        self.assertEqual(reasoning.status_code, 200)
        state = self.client.get("/api/projects/Mi%20Peque%C3%B1o%20Sol/chat-state")
        self.assertEqual(state.status_code, 200)
        self.assertEqual(state.json()["reasoning_mode"], "deep")
        self.assertEqual(state.json()["history"], [])
        self.assertEqual(state.json()["archives"], [])
        self.assertTrue(state.json()["conversation_id"])

    def test_chat_can_be_archived_restored_and_cleared(self):
        project = "Mi Pequeño Sol"
        initial = self.client.get(
            "/api/projects/Mi%20Peque%C3%B1o%20Sol/chat-state"
        ).json()
        _record_chat_exchange(
            project,
            initial["conversation_id"],
            "hola",
            {"message": "hola Leo"},
        )

        archived = self.client.post(
            "/api/projects/Mi%20Peque%C3%B1o%20Sol/chat/archive"
        ).json()
        self.assertEqual(archived["history"], [])
        self.assertEqual(len(archived["archives"]), 1)
        self.assertNotEqual(archived["conversation_id"], initial["conversation_id"])

        archive_id = archived["archives"][0]["archive_id"]
        restored = self.client.post(
            f"/api/projects/Mi%20Peque%C3%B1o%20Sol/chat/archives/{archive_id}/restore"
        ).json()
        self.assertEqual([item["content"] for item in restored["history"]], ["hola", "hola Leo"])
        self.assertEqual(restored["archives"], [])

        cleared = self.client.delete(
            "/api/projects/Mi%20Peque%C3%B1o%20Sol/chat/history"
        ).json()
        self.assertEqual(cleared["history"], [])
        self.assertEqual(cleared["archives"], [])

    def test_capability_map_is_available_without_reaper(self):
        response = self.client.get("/api/capabilities")
        self.assertEqual(response.status_code, 200)
        groups = response.json()["groups"]
        self.assertGreaterEqual(len(groups), 3)
        self.assertTrue(any(item["id"] == "producer_chain" for group in groups for item in group["items"]))

    @patch("pampapilot.web_server.subprocess.Popen")
    def test_compact_window_launcher_is_exposed(self, popen):
        response = self.client.post(
            "/api/window/compact", json={"project_name": "Mi Pequeño Sol"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "opening", "mode": "compact", "always_on_top": True},
        )
        popen.assert_called_once()
        self.assertIn("Mi Pequeño Sol", popen.call_args.args[0])

    def test_track_names_remain_stable_after_analysis_is_invalidated(self):
        names = _suggested_track_names(
            [{"name": "5 Drums"}, {"name": "6 Drums- OK"}, {"name": "7 Drums"}]
        )
        self.assertEqual(names["5 Drums"], "Drums 1")
        self.assertEqual(names["7 Drums"], "Drums 2")
        self.assertEqual(names["6 Drums- OK"], "Drums- OK")

    def test_empty_optional_file_inputs_are_not_treated_as_uploads(self):
        selected = UploadFile(BytesIO(b"RIFF"), filename="DE LA LLUVIA.wav")
        empty_midi = UploadFile(BytesIO(b""), filename="")

        self.assertEqual(_named_uploads([selected, empty_midi]), [selected])

    def test_project_upload_accepts_a_stem_with_empty_optional_file_fields(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                patch("pampapilot.web_server.WORKSPACE_ROOT", root),
                patch(
                    "pampapilot.web_server._project_view",
                    return_value={"name": "Drum De la lluvia"},
                ),
            ):
                response = self.client.post(
                    "/api/projects",
                    data={
                        "title": "Drum De la lluvia",
                        "bpm": "85",
                        "source_kind": "suno_stems",
                        "lyrics": "",
                    },
                    files=[
                        ("stems", ("DE LA LLUVIA.wav", b"RIFF", "audio/wav")),
                        ("midi", ("", b"", "application/octet-stream")),
                    ],
                )

            self.assertEqual(response.status_code, 201, response.text)
            self.assertTrue(
                (root / "media" / "inbox" / "stems" / "Drum De la lluvia" / "DE LA LLUVIA.wav").is_file()
            )

    def test_project_can_be_created_without_media(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                patch("pampapilot.web_server.WORKSPACE_ROOT", root),
                patch("pampapilot.web_server._project_view", return_value={"name": "Borrador"}),
            ):
                response = self.client.post(
                    "/api/projects",
                    data={"title": "Borrador", "bpm": "92", "source_kind": "unknown", "lyrics": ""},
                )

            self.assertEqual(response.status_code, 201, response.text)
            self.assertTrue((root / "media" / "inbox" / "stems" / "Borrador" / "session.json").is_file())

    def test_configured_stem_order_is_deterministic(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "media" / "inbox" / "stems" / "Song"
            directory.mkdir(parents=True)
            for name in ("Bass.wav", "Drums.wav", "Vocals.wav"):
                (directory / name).write_bytes(b"RIFF")
            with (
                patch("pampapilot.web_server.WORKSPACE_ROOT", root),
                patch("pampapilot.web_server._project_metadata", return_value={"stem_order": ["Vocals", "Drums", "Bass"]}),
            ):
                ordered = _ordered_stem_paths("Song")
            self.assertEqual([path.stem for path in ordered], ["Vocals", "Drums", "Bass"])

    def test_reaper_sync_creates_project_and_imports_only_missing_sources(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            stem = root / "media" / "inbox" / "stems" / "Song" / "Vocals.wav"
            stem.parent.mkdir(parents=True)
            stem.write_bytes(b"RIFF")
            metadata = {"tempo_bpm": 85, "source_kind": "suno_stems"}
            client = unittest.mock.MagicMock()

            def call(action, params=None, **_kwargs):
                results = {
                    "create_song_project": {"project_ref": "song-ref"},
                    "get_track_items": {"items": []},
                    "import_audio_batch": {"imported_count": 1},
                    "reorder_audio_tracks_by_source": {"reordered_count": 1},
                    "set_project_tempo": {"tempo_bpm": 85},
                    "save_project_as": {"track_count": 1},
                }
                return SimpleNamespace(result=results[action])

            client.call.side_effect = call
            with (
                patch("pampapilot.web_server.WORKSPACE_ROOT", root),
                patch("pampapilot.web_server._project_metadata", return_value=metadata),
                patch("pampapilot.web_server._write_project_metadata"),
                patch("pampapilot.web_server._project_view", return_value={"name": "Song", "stems": [{"name": "Vocals", "track_name": "Vocals"}]}),
                patch("pampapilot.web_server.BridgeClient", return_value=client),
                patch("pampapilot.web_server.bridge_project", side_effect=[
                    {"result": {"project_path": "", "project_ref": "empty", "tracks": []}},
                    {"result": {"project_path": str(root / "sessions" / "Song" / "Song.rpp"), "project_ref": "song-ref", "tracks": []}},
                ]),
            ):
                response = self.client.post("/api/projects/Song/reaper-sync")

            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["imported_count"], 1)
            actions = [entry.args[0] for entry in client.call.call_args_list]
            self.assertEqual(actions, ["create_song_project", "import_audio_batch", "reorder_audio_tracks_by_source", "set_project_tempo", "save_project_as"])

    @patch("pampapilot.web_server.LMStudioClient.chat_result")
    @patch("pampapilot.web_server.build_project_context")
    def test_chat_creates_non_executable_approval_proposal(self, context, chat):
        context.return_value = {"song": {"title": "Test"}, "stems": []}
        from pampapilot.lmstudio_client import LMStudioChatResult

        chat.return_value = LMStudioChatResult(
            content=(
                '{"message":"Conviene comparar.","proposal":'
                '{"title":"A/B","summary":"Prueba segura","risk":"low",'
                '"changes":[{"target":"Voz","action":"A/B compresión",'
                '"reason":"Evaluar dinámica"}]}}'
            ),
            response_id="resp_test",
            stats={"time_to_first_token_seconds": 0.5},
        )

        response = self.client.post(
            "/api/chat",
            json={"project_name": "Test", "message": "analizá", "history": [], "conversation_id": "test-conversation"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["context_level"], "deep")
        proposal = response.json()["proposal"]
        self.assertEqual(proposal["status"], "pending")
        decision = self.client.post(
            f"/api/proposals/{proposal['proposal_id']}/decision",
            json={"decision": "apply"},
        ).json()
        self.assertFalse(decision["executable"])
        self.assertEqual(decision["status"], "awaiting_deterministic_mapping")

    @patch("pampapilot.web_server.runtime.approval_mode", return_value="manual")
    @patch("pampapilot.web_server._build_chat_action_plan")
    @patch("pampapilot.web_server.LMStudioClient.chat_result")
    @patch("pampapilot.web_server.build_project_context")
    def test_chat_typed_actions_create_executable_plan(
        self, context, chat, build_plan, _approval_mode
    ):
        from pampapilot.lmstudio_client import LMStudioChatResult

        context.return_value = {"song": {"title": "Test"}, "stems": []}
        chat.return_value = LMStudioChatResult(
            '{"message":"Preparé el cambio","proposal":null,"actions":['
            '{"kind":"static_mix","target":"Percussion","volume_delta_db":-2}]}',
            "typed-action",
            {},
        )
        build_plan.return_value = {
            "title": "Plan",
            "summary": "Un cambio",
            "risk": "low",
            "requires_approval": True,
            "changes": [{"target": "Percussion", "action": "-2 dB", "reason": "pedido"}],
            "project_name": "Test",
            "project_ref": "project.rpp",
            "operations": [{"kind": "static_mix", "items": []}],
            "executable": True,
        }

        response = self.client.post(
            "/api/chat",
            json={
                "project_name": "Test",
                "message": "bajá 2 dB la percusión",
                "history": [],
                "conversation_id": "typed-plan-test",
            },
        )

        self.assertEqual(response.status_code, 200)
        proposal = response.json()["proposal"]
        self.assertTrue(proposal["executable"])
        self.assertEqual(proposal["status"], "pending")
        self.assertEqual(chat.call_args.kwargs["reasoning"], "on")

    @patch("pampapilot.web_server.LMStudioClient.chat_result")
    @patch("pampapilot.web_server.build_project_context")
    def test_direct_action_retries_malformed_model_json(self, context, chat):
        from pampapilot.lmstudio_client import LMStudioChatResult

        context.return_value = {
            "song": {"title": "Test"},
            "stems": [{"name": "1 Percussion", "role": "percussion"}],
        }
        chat.side_effect = [
            LMStudioChatResult('```json\n{"message":"paneo","actions":[', "broken", {}),
            LMStudioChatResult(
                '{"message":"Preparé el paneo","proposal":null,"actions":[]}',
                "repaired",
                {},
            ),
        ]

        response = self.client.post(
            "/api/chat",
            json={
                "project_name": "Test",
                "message": "paneá la percu a la izquierda",
                "history": [],
                "conversation_id": "repair-json-test",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["message"], "Preparé el paneo")
        self.assertEqual(chat.call_count, 2)
        self.assertEqual(chat.call_args_list[1].kwargs["previous_response_id"], "broken")

    @patch("pampapilot.web_server.LMStudioClient.chat_result")
    @patch("pampapilot.web_server.build_project_context")
    def test_same_project_conversation_reuses_response_id(self, context, chat):
        from pampapilot.lmstudio_client import LMStudioChatResult

        context.return_value = {"song": {"title": "Test"}, "stems": []}
        chat.side_effect = [
            LMStudioChatResult('{"message":"Hola","proposal":null}', "resp_one", {}),
            LMStudioChatResult('{"message":"Seguimos","proposal":null}', "resp_two", {}),
        ]
        payload = {
            "project_name": "Test",
            "history": [],
            "conversation_id": "persistent-test-chat",
        }
        first = self.client.post("/api/chat", json={**payload, "message": "hola"})
        second = self.client.post("/api/chat", json={**payload, "message": "seguimos"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertIsNone(chat.call_args_list[0].kwargs["previous_response_id"])
        self.assertEqual(
            chat.call_args_list[1].kwargs["previous_response_id"], "resp_one"
        )
        self.assertEqual(context.call_count, 1)

    @patch("pampapilot.web_server._resolve_agent_evidence")
    @patch("pampapilot.web_server.LMStudioClient.chat_result")
    @patch("pampapilot.web_server.build_project_context")
    def test_chat_resolves_one_bounded_evidence_round(self, context, chat, resolve):
        from pampapilot.lmstudio_client import LMStudioChatResult

        context.return_value = {"song": {"title": "Test"}, "stems": []}
        resolve.return_value = {
            "agent_protocol": {"name": "pampapilot-agent", "version": "1.0", "message_type": "result"},
            "status": "ok",
            "data": {"evidence": [{"evidence_type": "project_analysis", "status": "ok"}]},
        }
        chat.side_effect = [
            LMStudioChatResult(
                '{"protocol_version":"1.0","message":"Necesito datos",'
                '"proposal":null,"actions":[{"kind":"request_evidence",'
                '"evidence_type":"project_analysis"}]}',
                "need-evidence", {},
            ),
            LMStudioChatResult(
                '{"protocol_version":"1.0","message":"Ya puedo responder",'
                '"proposal":null,"actions":[]}',
                "final-evidence", {},
            ),
        ]

        response = self.client.post(
            "/api/chat",
            json={
                "project_name": "Test",
                "message": "analizá la compresión",
                "history": [],
                "conversation_id": "evidence-round-test",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["message"], "Ya puedo responder")
        self.assertEqual(chat.call_count, 2)
        self.assertEqual(chat.call_args_list[1].kwargs["previous_response_id"], "need-evidence")
        resolve.assert_called_once()

    @patch("pampapilot.web_server.LMStudioClient.chat_result")
    @patch("pampapilot.web_server.build_project_context")
    def test_chat_reasoning_mode_overrides_automatic_selection(self, context, chat):
        from pampapilot.lmstudio_client import LMStudioChatResult

        context.return_value = {"song": {"title": "Test"}, "stems": []}
        chat.return_value = LMStudioChatResult('{"message":"Respuesta","proposal":null}', "reasoning-mode", {})

        response = self.client.post(
            "/api/chat",
            json={
                "project_name": "Test",
                "message": "analizá y proponé una mejora",
                "history": [],
                "conversation_id": "reasoning-mode-test",
                "reasoning_mode": "fast",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(chat.call_args.kwargs["reasoning"], "off")
        self.assertEqual(response.json()["reasoning_mode"], "fast")
        self.assertFalse(response.json()["reasoning_used"])

    @patch("pampapilot.web_server.LMStudioClient.chat_result")
    @patch("pampapilot.web_server.build_project_context")
    def test_deep_chat_refreshes_context_when_analysis_changes(self, context, chat):
        from pampapilot.lmstudio_client import LMStudioChatResult

        context.side_effect = [
            {"song": {"title": "Test"}, "analysis": None},
            {"song": {"title": "Test"}, "analysis": {"summary": {"stem_count": 2}}},
        ]
        chat.side_effect = [
            LMStudioChatResult('{"message":"Primero","proposal":null}', "analysis-one", {}),
            LMStudioChatResult('{"message":"Actualizado","proposal":null}', "analysis-two", {}),
        ]
        payload = {
            "project_name": "Test",
            "message": "analizá los stems",
            "history": [],
            "conversation_id": "analysis-refresh-test",
        }

        first = self.client.post("/api/chat", json=payload)
        second = self.client.post("/api/chat", json=payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(chat.call_args_list[1].kwargs["previous_response_id"], "analysis-one")
        self.assertIn("actualizó el contexto técnico", chat.call_args_list[1].args[0][0]["content"])


if __name__ == "__main__":
    unittest.main()
