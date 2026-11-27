import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import clipboard_utils


class ClipboardUtilsTests(unittest.TestCase):
    def test_decodes_chinese_unicode_text_and_trailing_terminator(self):
        value = "带宽\tB1200\r\n轴径\t14轴"
        raw = value.encode("utf-16-le") + b"\x00\x00"
        self.assertEqual(clipboard_utils.decode_unicode_clipboard_data(raw), value)

    def test_ascii_zero_bytes_are_not_mistaken_for_terminator(self):
        value = "A中文"
        raw = value.encode("utf-16-le") + b"\x00\x00"
        self.assertEqual(clipboard_utils.decode_unicode_clipboard_data(raw), value)

    def test_empty_clipboard_payload_decodes_to_empty_string(self):
        self.assertEqual(clipboard_utils.decode_unicode_clipboard_data(b"\x00\x00"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
