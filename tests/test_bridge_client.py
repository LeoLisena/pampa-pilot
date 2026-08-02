from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import time
import unittest

from productor_musical.bridge_client import BridgeClient, BridgeError
from productor_musical.protocol import Response


class BridgeClientTests(unittest.TestCase):
    def _respond_once(self, client: BridgeClient, *, status: str = "ok") -> threading.Thread:
        def worker() -> None:
            deadline = time.monotonic() + 1
            claimed = None
            while claimed is None and time.monotonic() < deadline:
                claimed = client.ipc.claim_oldest()
                time.sleep(0.001)
            assert claimed is not None
            error = None
            result = {"bridge_version": "test"}
            if status != "ok":
                error = {"code": "test_failure", "message": "fallo controlado"}
                result = {}
            client.ipc.complete(
                claimed,
                Response(
                    request_id=claimed.request.request_id,
                    status=status,
                    completed_at_ms=int(time.time() * 1000),
                    result=result,
                    error=error,
                    observations={"state_verified": status == "ok"},
                ),
            )

        thread = threading.Thread(target=worker)
        thread.start()
        return thread

    def test_call_returns_correlated_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            client = BridgeClient(Path(temporary), timeout_seconds=1)
            thread = self._respond_once(client)

            response = client.call("health_check")
            thread.join()

            self.assertEqual(response.result["bridge_version"], "test")
            self.assertTrue(response.observations["state_verified"])

    def test_bridge_error_preserves_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            client = BridgeClient(Path(temporary), timeout_seconds=1)
            thread = self._respond_once(client, status="error")

            with self.assertRaises(BridgeError) as raised:
                client.call("health_check")
            thread.join()

            self.assertEqual(raised.exception.code, "test_failure")

    def test_unknown_action_never_reaches_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            client = BridgeClient(Path(temporary), timeout_seconds=1)

            with self.assertRaises(LookupError):
                client.call("execute_lua")

            self.assertEqual(list(client.ipc.pending.glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()

