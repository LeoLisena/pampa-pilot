from __future__ import annotations

import json
import unittest

from pampapilot.protocol import ProtocolError, Request, Response


class RequestTests(unittest.TestCase):
    def test_round_trip_preserves_unicode_and_fields(self) -> None:
        request = Request.new(
            "set_track_pan",
            {"track_guid": "{TRACK-1}", "label": "Guitarra rítmica", "pan": -0.25},
            now_ms=1_000,
            timeout_ms=500,
        )

        decoded = Request.from_json_bytes(request.to_json_bytes())

        self.assertEqual(decoded, request)
        self.assertFalse(decoded.is_expired(1_500))
        self.assertTrue(decoded.is_expired(1_501))

    def test_rejects_unknown_protocol_version(self) -> None:
        request = Request.new("health_check", now_ms=1_000)
        value = json.loads(request.to_json_bytes())
        value["version"] = "99"

        with self.assertRaisesRegex(ProtocolError, "versión incompatible"):
            Request.from_json_bytes(json.dumps(value).encode())

    def test_rejects_invalid_action_name(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "action"):
            Request.new("execute arbitrary lua", now_ms=1_000)


class ResponseTests(unittest.TestCase):
    def test_error_requires_structured_error(self) -> None:
        request = Request.new("health_check", now_ms=1_000)
        response = Response(
            request_id=request.request_id,
            status="error",
            completed_at_ms=1_001,
        )

        with self.assertRaisesRegex(ProtocolError, "debe contener error"):
            response.to_json_bytes()

    def test_success_round_trip(self) -> None:
        request = Request.new("health_check", now_ms=1_000)
        response = Response(
            request_id=request.request_id,
            status="ok",
            completed_at_ms=1_001,
            result={"reaper_version": "7.78"},
            observations={"state_verified": True},
        )

        self.assertEqual(Response.from_json_bytes(response.to_json_bytes()), response)


if __name__ == "__main__":
    unittest.main()
