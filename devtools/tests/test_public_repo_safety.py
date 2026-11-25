import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

class PublicRepoSafetyTests(unittest.TestCase):
    def test_no_user_drawing_or_database_files_are_tracked(self):
        forbidden = {'.exb', '.sqlite', '.sqlite3', '.db', '.bak'}
        found = [p for p in ROOT.rglob('*') if p.is_file() and p.suffix.lower() in forbidden]
        self.assertEqual(found, [])

    def test_update_config_points_to_public_raw_manifest(self):
        cfg = json.loads((ROOT / 'updates' / 'update_source.json').read_text(encoding='utf-8'))
        self.assertTrue(cfg['manifest_url'].startswith('https://raw.githubusercontent.com/'))
        self.assertTrue(cfg['manifest_url'].endswith('/updates/manifest.json'))

    def test_updater_only_allows_program_directories(self):
        source = (ROOT / 'runtime' / 'updater.py').read_text(encoding='utf-8')
        self.assertIn('("app", "runtime")', source)
        self.assertIn('MAX_TOTAL_BYTES', source)

    def test_private_data_location_is_local_appdata(self):
        source = (ROOT / 'app' / 'core.py').read_text(encoding='utf-8')
        self.assertIn('LOCALAPPDATA', source)
        self.assertIn('CAXA_Library_Helper', source)

if __name__ == '__main__':
    unittest.main(verbosity=2)