import os
from pathlib import Path
import tempfile
import unittest

from pampapilot.secret_store import WindowsSecretStore


@unittest.skipUnless(os.name == "nt", "DPAPI is Windows-specific")
class WindowsSecretStoreTests(unittest.TestCase):
    def test_round_trip_is_user_scoped_and_not_plaintext(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token.dpapi"
            store = WindowsSecretStore(path)
            token = "private-development-token"

            store.save(token)

            self.assertTrue(store.exists())
            self.assertNotIn(token.encode("utf-8"), path.read_bytes())
            self.assertEqual(store.load(), token)
            store.clear()
            self.assertFalse(store.exists())
