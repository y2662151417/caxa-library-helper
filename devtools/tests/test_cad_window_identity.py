import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import cad_window


class CadWindowIdentityTests(unittest.TestCase):
    def test_exact_work_copy_caption_matches(self):
        self.assertTrue(cad_window.title_has_exact_work_file(
            "CAXA CAD - CRB01D2084_垂直重锤拉紧装置__图库制作.exb",
            "CRB01D2084_垂直重锤拉紧装置__图库制作.exb",
        ))

    def test_filename_substrings_do_not_match(self):
        filename = "CRB01D2084_垂直重锤拉紧装置__图库制作.exb"
        self.assertFalse(cad_window.title_has_exact_work_file("备份" + filename, filename))
        self.assertFalse(cad_window.title_has_exact_work_file(filename + ".bak", filename))
        self.assertFalse(cad_window.title_has_exact_work_file(
            "CRB01D2084_垂直重锤拉紧装置__图库制作2.exb", filename
        ))

    def test_cad_process_is_read_from_ini(self):
        self.assertEqual(
            cad_window.parse_cad_process_ini("[cad]\nprocess=CAXA.exe\n"),
            "CAXA.exe",
        )

    def test_missing_process_binding_is_empty(self):
        self.assertEqual(cad_window.parse_cad_process_ini("[cad]\nother=value\n"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
