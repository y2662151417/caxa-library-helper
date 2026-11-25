import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "devtools"))
import migrate_to_e


class MigrationCopyTests(unittest.TestCase):
    def test_repository_copy_preserves_git_and_excludes_runtime_logs(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            destination = base / "destination"
            (source / ".git").mkdir(parents=True)
            (source / ".git" / "config").write_text("[remote \"origin\"]\n", encoding="utf-8")
            (source / "app").mkdir()
            (source / "app" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            (source / "logs").mkdir()
            (source / "logs" / "startup.log").write_text("legacy\n", encoding="utf-8")
            (source / "logs" / "README.txt").write_text("repository documentation\n", encoding="utf-8")
            (source / "app" / "__pycache__").mkdir()
            (source / "app" / "__pycache__" / "temp.pyc").write_bytes(b"cache")

            stats = migrate_to_e.copy_repository(source, destination)

            self.assertTrue((destination / ".git" / "config").is_file())
            self.assertTrue((destination / "app" / "app.py").is_file())
            self.assertEqual(
                (destination / "logs" / "README.txt").read_text(encoding="utf-8"),
                "repository documentation\n",
            )
            self.assertFalse((destination / "logs" / "startup.log").exists())
            self.assertFalse((destination / "app" / "__pycache__").exists())
            self.assertTrue(stats["git_metadata_preserved"])

    def test_user_data_copy_uses_sqlite_backup_and_checks_rows(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            destination = base / "destination"
            source.mkdir()
            (source / "cad_buttons.ini").write_text("[buttons]\n", encoding="utf-8")
            database = sqlite3.connect(source / migrate_to_e.DATABASE_NAME)
            database.execute("CREATE TABLE drawings (path TEXT PRIMARY KEY, status TEXT)")
            database.executemany(
                "INSERT INTO drawings(path,status) VALUES (?,?)",
                [("A.exb", "待处理"), ("B.exb", "已完成")],
            )
            database.commit()
            database.close()

            stats = migrate_to_e.copy_user_data(source, destination)

            copied = sqlite3.connect(destination / migrate_to_e.DATABASE_NAME)
            self.assertEqual(copied.execute("PRAGMA quick_check").fetchone()[0], "ok")
            self.assertEqual(copied.execute("SELECT COUNT(*) FROM drawings").fetchone()[0], 2)
            copied.close()
            self.assertEqual(stats["database"]["table_rows"]["drawings"], 2)
            self.assertEqual(
                (destination / "cad_buttons.ini").read_text(encoding="utf-8"),
                "[buttons]\n",
            )


    def test_migration_launcher_checks_drive_with_python_and_uses_default_path(self):
        source = (ROOT / "迁移到E盘.bat").read_text(encoding="utf-8")
        self.assertIn("os.path.isdir('E:/')", source)
        self.assertNotIn('E:\\NUL', source)
        self.assertIn('%PY% "devtools\\migrate_to_e.py"', source)
        self.assertNotIn('--target-root', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
