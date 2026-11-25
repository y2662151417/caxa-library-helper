import copy
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
import profiles

EXAMPLE = Path(__file__).resolve().parents[2] / 'app' / 'resources' / '图库模板_示例.json'
class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.p,self.generic=profiles.read_profiles(EXAMPLE)
    def test_two_templates_and_6_view_limit(self):
        self.assertEqual(len(self.p['view_plan']),6)
        self.assertEqual(self.generic['view_plan'],[])
    def test_file_with_chinese_title_and_multiple_underscores(self):
        self.assertEqual(profiles.filename_info('SAMPLE-005_拉紧_装置.EXB'),{'图号':'SAMPLE-005','图名':'拉紧_装置'})
    def test_parameter_copy(self):
        raw='带宽\tB1200\n轴径\t14轴\n筒径\tD800\n'
        info=profiles.parse_property_grid(raw,self.p)
        self.assertEqual(info,{'带宽':'B1200','轴径':'14轴','筒径':'D800'})
        self.assertEqual(profiles.build_name('SAMPLE-005_垂直重锤拉紧装置.exb',self.p,info),'SAMPLE-005_垂直重锤拉紧装置_B1200_14轴_D800')
    def test_missing_param_blocks_name(self):
        with self.assertRaises(profiles.ProfileError):
            profiles.build_name('A_机架.exb',self.p,{'带宽':'B800'})
    def test_conflicting_values_blocked(self):
        with self.assertRaises(profiles.ProfileError):
            profiles.parse_property_grid('带宽\tB800\n带宽\tB1000',self.p)
    def test_unknown_color_rules_not_executable(self):
        self.assertEqual(profiles.auto_executable_colors(self.p),[])
    def test_all_rules_specified_but_only_explicit_value_active(self):
        p=copy.deepcopy(self.p)
        p['color_rules'][0].update(target_linetype='CENTER',linetype_scale=1.0)
        self.assertEqual(len(profiles.auto_executable_colors(p)),1)
    def test_more_than_six_rejected(self):
        p=copy.deepcopy(self.p);p['view_plan'].append({'view':'剖视图','kind':'带尺寸'})
        with self.assertRaises(profiles.ProfileError):profiles.validate(p)
    def test_duplicate_view_rejected(self):
        p=copy.deepcopy(self.p);p['view_plan'][1]=p['view_plan'][0]
        with self.assertRaises(profiles.ProfileError):profiles.validate(p)
    def test_generic_name(self):
        self.assertEqual(profiles.build_name('XX-01_机架.exb',self.generic),'XX-01_机架')
    def test_invalid_filename(self):
        with self.assertRaises(profiles.ProfileError):profiles.filename_info('unknown.exb')
    def test_parameter_alias_with_numeric_row(self):
        self.assertEqual(profiles.parse_property_grid('1\t皮带宽度\tB1400',self.p),{'带宽':'B1400'})
if __name__=='__main__': unittest.main(verbosity=2)