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

    def test_private_data_location_supports_e_drive_override_and_legacy_fallback(self):
        source = (ROOT / 'app' / 'core.py').read_text(encoding='utf-8')
        self.assertIn('CAXA_HELPER_DATA_DIR', source)
        self.assertIn('LOCALAPPDATA', source)
        self.assertIn('CAXA_Library_Helper', source)


    def test_startup_does_not_rewrite_existing_update_config(self):
        source = (ROOT / '启动CAXA助手.bat').read_text(encoding='utf-8')
        self.assertIn('if not exist "updates\\update_source.json"', source)
        self.assertIn("p.write_text(json.dumps(d", source)

if __name__ == '__main__':
    unittest.main(verbosity=2)
