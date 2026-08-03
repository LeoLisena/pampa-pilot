import io
import json
import unittest
from unittest.mock import patch

from pampapilot.lmstudio_client import (
    LMStudioClient,
    LMStudioConfig,
    LMStudioError,
    normalize_base_url,
)


class _Response:
    def __init__(self, value):
        self._payload = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self._payload


class LMStudioClientTests(unittest.TestCase):
    def test_normalizes_valid_url_and_rejects_embedded_credentials(self):
        self.assertEqual(normalize_base_url(" http://localhost:1234/ "), "http://localhost:1234")
        with self.assertRaises(ValueError):
            normalize_base_url("http://user:secret@localhost:1234")

    @patch("pampapilot.lmstudio_client.urlopen")
    def test_lists_models_without_exposing_token(self, mocked_urlopen):
        mocked_urlopen.return_value = _Response({"data": [{"id": "google/gemma"}]})
        client = LMStudioClient(
            LMStudioConfig(base_url="http://localhost:1234", token="private")
        )

        self.assertEqual(client.list_models(), ["google/gemma"])
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer private")

    @patch("pampapilot.lmstudio_client.urlopen")
    def test_extracts_openai_compatible_chat_content(self, mocked_urlopen):
        mocked_urlopen.return_value = _Response(
            {"choices": [{"message": {"content": '{"message":"ok"}'}}]}
        )
        client = LMStudioClient(
            LMStudioConfig(
                base_url="http://localhost:1234",
                model="gemma",
                authentication_required=False,
            )
        )

        self.assertEqual(
            client.chat([{"role": "user", "content": "hola"}]),
            '{"message":"ok"}',
        )
        request = mocked_urlopen.call_args.args[0]
        body = json.loads(io.BytesIO(request.data).read().decode("utf-8"))
        self.assertEqual(body["model"], "gemma")
        self.assertFalse(body["stream"])

    @patch("pampapilot.lmstudio_client.urlopen")
    def test_rejects_malformed_model_response(self, mocked_urlopen):
        mocked_urlopen.return_value = _Response({"models": []})
        with self.assertRaises(LMStudioError):
            LMStudioClient(LMStudioConfig(authentication_required=False)).list_models()

    def test_requires_token_by_default(self):
        with self.assertRaisesRegex(LMStudioError, "token is required"):
            LMStudioClient(LMStudioConfig()).list_models()


if __name__ == "__main__":
    unittest.main()
