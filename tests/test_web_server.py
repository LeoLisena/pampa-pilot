import unittest
from unittest.mock import patch
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from pampapilot.web_server import _named_uploads, _suggested_track_names, app, runtime


class WebServerTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

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

    def test_capability_map_is_available_without_reaper(self):
        response = self.client.get("/api/capabilities")
        self.assertEqual(response.status_code, 200)
        groups = response.json()["groups"]
        self.assertGreaterEqual(len(groups), 3)
        self.assertTrue(any(item["id"] == "producer_chain" for group in groups for item in group["items"]))

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
