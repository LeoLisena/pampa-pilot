import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from pampapilot.web_server import app, runtime


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
