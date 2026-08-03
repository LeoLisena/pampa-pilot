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

    def test_public_settings_never_return_token(self):
        response = self.client.get("/api/settings/brain")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("token", response.json())
        self.assertTrue(response.json()["authentication_required"])

    @patch("pampapilot.web_server.LMStudioClient.chat")
    @patch("pampapilot.web_server.build_project_context")
    def test_chat_creates_non_executable_approval_proposal(self, context, chat):
        context.return_value = {"song": {"title": "Test"}, "stems": []}
        chat.return_value = (
            '{"message":"Conviene comparar.","proposal":'
            '{"title":"A/B","summary":"Prueba segura","risk":"low",'
            '"changes":[{"target":"Voz","action":"A/B compresión",'
            '"reason":"Evaluar dinámica"}]}}'
        )

        response = self.client.post(
            "/api/chat",
            json={"project_name": "Test", "message": "analizá", "history": []},
        )

        self.assertEqual(response.status_code, 200)
        proposal = response.json()["proposal"]
        self.assertEqual(proposal["status"], "pending")
        decision = self.client.post(
            f"/api/proposals/{proposal['proposal_id']}/decision",
            json={"decision": "apply"},
        ).json()
        self.assertFalse(decision["executable"])
        self.assertEqual(decision["status"], "awaiting_deterministic_mapping")


if __name__ == "__main__":
    unittest.main()
