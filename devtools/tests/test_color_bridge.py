import configparser
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
import bridge


class ColorBridgeTests(unittest.TestCase):
    def test_filtered_selection_action_is_allowlisted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = bridge.request_panel_action(Path(directory), 'select_filtered_objects', 'a' * 64)
            config = configparser.ConfigParser(interpolation=None)
            config.read(path, encoding='utf-16')
            self.assertEqual(config['request']['action'], 'select_filtered_objects')
            self.assertEqual(config['request']['job_signature'], 'a' * 64)

    def test_four_property_calibration_actions_are_allowlisted(self):
        for action in ('calibrate_layer_combo', 'calibrate_color_combo',
                       'calibrate_linetype_combo', 'calibrate_lineweight_combo'):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as directory:
                path = bridge.request_panel_action(Path(directory), action, 'b' * 64)
                config = configparser.ConfigParser(interpolation=None)
                config.read(path, encoding='utf-16')
                self.assertEqual(config['request']['action'], action)

    def test_apply_color_layer_requires_a_safe_target_layer(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                bridge.request_panel_action(Path(directory), 'apply_color_layer', 'c' * 64)
            with self.assertRaises(ValueError):
                bridge.request_panel_action(Path(directory), 'apply_color_layer', 'c' * 64,
                                            target_layer='中心线层\\n[bad]')

    def test_layer_visibility_actions_are_allowlisted(self):
        for action in ('open_layer_manager', 'open_all_layers'):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as directory:
                path = bridge.request_panel_action(Path(directory), action, 'e' * 64)
                config = configparser.ConfigParser(interpolation=None)
                config.read(path, encoding='utf-16')
                self.assertEqual(config['request']['action'], action)
                self.assertEqual(config['request']['job_signature'], 'e' * 64)

    def test_apply_color_layer_writes_target_layer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = bridge.request_panel_action(Path(directory), 'apply_color_layer', 'd' * 64,
                                                target_layer='中心线层')
            config = configparser.ConfigParser(interpolation=None)
            config.read(path, encoding='utf-16')
            self.assertEqual(config['request']['target_layer'], '中心线层')


if __name__ == '__main__':
    unittest.main(verbosity=2)
