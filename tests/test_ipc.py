from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from productor_musical.ipc import FilesystemIPC
from productor_musical.protocol import Request, Response


class FilesystemIPCTests(unittest.TestCase):
    def test_submit_claim_complete_and_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ipc = FilesystemIPC(Path(temporary))
            ipc.initialize()
            request = Request.new("health_check", now_ms=1_000, timeout_ms=5_000)

            pending_path = ipc.submit(request)
            self.assertTrue(pending_path.exists())
            self.assertEqual(list(ipc.pending.glob("*.tmp")), [])

            claimed = ipc.claim_oldest(now_ms=1_001)
            self.assertIsNotNone(claimed)
            assert claimed is not None
            self.assertFalse(pending_path.exists())
            self.assertTrue(claimed.path.exists())

            response = Response(
                request_id=request.request_id,
                status="ok",
                completed_at_ms=1_002,
                result={"bridge": "ready"},
                observations={"state_verified": True},
            )
            ipc.complete(claimed, response)

            self.assertFalse(claimed.path.exists())
            self.assertEqual(ipc.load_response(request.request_id), response)

    def test_expired_request_gets_response_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ipc = FilesystemIPC(Path(temporary))
            ipc.initialize()
            request = Request.new("create_track", now_ms=1_000, timeout_ms=10)
            ipc.submit(request)

            claimed = ipc.claim_oldest(now_ms=1_011)

            self.assertIsNone(claimed)
            response = ipc.load_response(request.request_id)
            self.assertIsNotNone(response)
            assert response is not None
            self.assertEqual(response.status, "expired")
            self.assertEqual(response.error["code"], "deadline_exceeded")

    def test_duplicate_pending_request_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ipc = FilesystemIPC(Path(temporary))
            ipc.initialize()
            request = Request.new("health_check", now_ms=1_000)
            ipc.submit(request)

            with self.assertRaises(FileExistsError):
                ipc.submit(request)

    def test_completed_request_cannot_be_submitted_again(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ipc = FilesystemIPC(Path(temporary))
            ipc.initialize()
            request = Request.new("health_check", now_ms=1_000)
            ipc.submit(request)
            claimed = ipc.claim_oldest(now_ms=1_001)
            assert claimed is not None
            ipc.complete(
                claimed,
                Response(
                    request_id=request.request_id,
                    status="ok",
                    completed_at_ms=1_002,
                ),
            )

            with self.assertRaises(FileExistsError):
                ipc.submit(request)


if __name__ == "__main__":
    unittest.main()
