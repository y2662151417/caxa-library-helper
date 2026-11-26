import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class UpdateManifestIntegrityTests(unittest.TestCase):
    def test_every_incremental_update_hash_matches_repository_file(self):
        manifest = json.loads((ROOT / "updates" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest.get("version"), (ROOT / "app" / "VERSION.txt").read_text(encoding="utf-8").strip())
        files = manifest.get("files")
        self.assertIsInstance(files, list)
        self.assertTrue(files, "update manifest must contain at least one program file")
        seen = set()
        for item in files:
            path_text = item.get("path", "")
            self.assertTrue(path_text)
            self.assertNotIn(path_text, seen, f"duplicate update path: {path_text}")
            seen.add(path_text)
            path = ROOT / path_text
            self.assertTrue(path.is_file(), f"manifest file is missing: {path_text}")
            data = path.read_bytes()
            self.assertEqual(item.get("size"), len(data), f"size mismatch: {path_text}")
            self.assertEqual(
                item.get("sha256"),
                hashlib.sha256(data).hexdigest(),
                f"SHA-256 mismatch: {path_text}",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
