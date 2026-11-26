import configparser
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import bridge


class ReadOnlyControlProbeTests(unittest.TestCase):
    def test_probe_action_is_allowlisted_and_task_signed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = bridge.request_panel_action(
                Path(folder), "probe_cad_controls", "a" * 64
            )
            cfg = configparser.ConfigParser(interpolation=None)
            cfg.read(path, encoding="utf-16")
            self.assertEqual(cfg["request"]["action"], "probe_cad_controls")
            self.assertEqual(cfg["request"]["job_signature"], "a" * 64)

    def test_arbitrary_panel_action_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                bridge.request_panel_action(Path(folder), "run_arbitrary_command", "a" * 64)

    def test_invalid_job_signature_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                bridge.request_panel_action(Path(folder), "probe_cad_controls", "not-a-signature")

    def test_controller_probe_function_contains_no_cad_input_or_click_calls(self):
        source = (ROOT / "app" / "快捷键工具" / "CAXA_半自动辅助.ahk").read_text(encoding="utf-8-sig")
        start = source.index("probeCaxaControls(expectedSignature) {")
        end = source.index("; When Symdef opens the gallery dialog", start)
        body = source[start:end]
        forbidden = re.compile(
            r"^\s*(?:SendText|SendInput|SendEvent|SendPlay|Send\s|Click\s*\(|"
            r"ControlClick\s*\(|ControlSend\s*\(|ControlSetText\s*\(|"
            r"WinActivate\s*\(|FileDelete\s|FileMove\s|Run\s*\()",
            re.MULTILINE,
        )
        self.assertIsNone(forbidden.search(body))
        self.assertIn("WinGetControls", body)
        self.assertIn("ControlGetPos", body)
        self.assertIn("FileAppend result", body)

    def test_standalone_probe_uses_configured_data_directory(self):
        source = (ROOT / "app" / "快捷键工具" / "CAXA_控件探针_只读.ahk").read_text(encoding="utf-8")
        self.assertIn('EnvGet("CAXA_HELPER_DATA_DIR")', source)
        self.assertIn('"1", "图层设置（尺寸线层）"', source)
        self.assertIn('"5", "图符入库"', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
