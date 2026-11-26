import copy
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
import profiles
import workflow_v08

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
    def test_only_colors_with_target_layers_are_executable(self):
        ready=profiles.auto_executable_colors(self.p)
        self.assertEqual([r['source_color'] for r in ready],['红色','绿色'])
    def test_target_layer_is_sufficient_without_per_entity_linetype_values(self):
        p=copy.deepcopy(self.p)
        p['color_rules']=[{'source_color':'红色','target_layer':'中心线层'},
                          {'source_color':'绿色','target_layer':None}]
        self.assertEqual([r['source_color'] for r in profiles.auto_executable_colors(p)],['红色'])
    def test_color_plan_ignores_unmapped_colors(self):
        plan=workflow_v08.safe_color_plan(self.p,selection_confirmed=True)
        self.assertEqual([r['source_color'] for r in plan],['红色','绿色'])
        self.assertEqual(plan[0]['target_layer'],'中心线层')
        self.assertEqual(plan[1]['target_layer'],'虚线层')
        self.assertEqual(plan[0]['target_properties'],{
            'layer':'中心线层','color':'ByLayer','linetype':'ByLayer','lineweight':'ByLayer'})
        self.assertIn('Ctrl+A',plan[0]['selection_method'])
    def test_color_rule_instruction_requires_selection_review(self):
        rule=workflow_v08.validate_color_rule(self.p,'红色')
        instruction=workflow_v08.color_rule_instruction(rule)
        self.assertIn('Ctrl+A',instruction)
        self.assertIn('按 Esc 取消',instruction)
        self.assertIn('ByLayer',instruction)
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