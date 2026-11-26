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

    def test_controller_probe_is_one_shot_and_read_only(self):
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
        self.assertIn('WinGetList("ahk_pid " pid)', body)
        self.assertIn('WinGetControls("ahk_id " hwnd)', body)
        self.assertIn("ControlGetHwnd", body)
        self.assertIn("ControlGetPos", body)
        for token in (
            "GetClassNameW",
            "GetDlgCtrlID",
            "IsWindowVisible",
            "IsWindowEnabled",
            "GetWindowLongPtrW",
            "GetWindowLongW",
            "Win32Class:",
            "ControlID:",
            "Visible:",
            "Enabled:",
            "Style:",
            "ExStyle:",
        ):
            self.assertIn(token, body)
        self.assertIn("controls_all_", body)
        self.assertIn("maxWindows := 20", body)
        self.assertIn("maxControls := 1200", body)
        self.assertIn("maxControlsPerWindow := 300", body)
        self.assertNotIn("InputBox(", body)
        self.assertNotIn("findUniqueVisibleProbeDialog", source)
        self.assertNotIn("WinGetText", body)
        self.assertNotIn("ControlGetText", body)
        self.assertIn("titleHasExactWorkFile", body)
        self.assertIn("verifyBeforeAction", body)
        self.assertIn("0x10000000", body)

    def test_standalone_probe_uses_configured_data_directory(self):
        source = (ROOT / "app" / "快捷键工具" / "CAXA_控件探针_只读.ahk").read_text(encoding="utf-8")
        self.assertIn('EnvGet("CAXA_HELPER_DATA_DIR")', source)
        self.assertIn('"1", "图层设置（尺寸线层）"', source)
        self.assertIn('"5", "图符入库"', source)

    def test_standalone_probe_uses_guarded_single_key(self):
        source = (ROOT / "app" / "快捷键工具" / "CAXA_控件探针_只读.ahk").read_text(encoding="utf-8")
        active_hotkeys = [line.strip() for line in source.splitlines()
                          if "::" in line and not line.lstrip().startswith(";")]
        self.assertEqual(active_hotkeys, ["F2::{"])
        self.assertIn("#HotIf isConfiguredCaxaForeground()", source)
        self.assertIn('WinGetProcessName("A")', source)
        self.assertNotRegex(source, r"(?m)^\s*\^!.*::")


if __name__ == "__main__":
    unittest.main(verbosity=2)
