import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import core

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def column_name(number):
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def write_xlsx(path, rows):
    row_xml = []
    for row_number, values in enumerate(rows, 1):
        cells = []
        for column, value in enumerate(values, 1):
            if value is None or value == "":
                continue
            ref = f"{column_name(column)}{row_number}"
            if isinstance(value, (int, float)):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
        row_xml.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    worksheet = f'<worksheet xmlns="{MAIN_NS}"><sheetData>{"".join(row_xml)}</sheetData></worksheet>'
    workbook = (
        f'<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}">'
        '<sheets><sheet name="配置" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    relationships = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)


class CaxaWorkbookConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source_dir = self.root / "source"
        self.source_dir.mkdir()
        self.source1 = self.source_dir / "CRB01D2084_垂直重锤拉紧装置.exb"
        self.source2 = self.source_dir / "CRB03D2126_垂直重锤拉紧装置.exb"
        self.source1.write_bytes(b"synthetic source 1")
        self.source2.write_bytes(b"synthetic source 2")
        self.db = core.connect(self.root / "progress.sqlite3")
        core.scan_folder(self.db, self.source_dir, exclude_dirs=())

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def workbook_rows(self):
        return [
            ["图号", "文件名（文件夹里的）", "块名称"],
            ["CRB01D2084", self.source1.name, "CRB01D2084_垂直重锤拉紧装置_B500_08轴_D500"],
            ["CRB03D2126", self.source2.name, "CRB03D2126_垂直重锤拉紧装置_B800_12轴_D800"],
            [None, None, None],
            [None, None, None],
            ["线层", "线型", "线型比例", "线宽", "颜色"],
            ["0层", None, 1, None, "白色（ByLayer）"],
        ]

    def test_imports_user_workbook_layout_and_confirmed_default_rules(self):
        workbook = self.root / "测试.xlsx"
        write_xlsx(workbook, self.workbook_rows())
        result = core.import_caxa_workbook_xlsx(self.db, workbook)
        self.assertEqual(result, {"drawing_count": 2, "color_rule_count": 5})

        first = core.block_name_for_path(self.db, str(self.source1))
        self.assertEqual(first["status"], "已匹配")
        self.assertEqual(first["drawing_filename"], self.source1.name)
        self.assertEqual(first["block_name"], "CRB01D2084_垂直重锤拉紧装置_B500_08轴_D500")

        rules = {r["source_color"]: r for r in core.get_cad_color_rules(self.db)}
        self.assertEqual(rules["红色"]["target_layer"], "中心线层")
        self.assertEqual(rules["绿色"]["target_layer"], "虚线层")
        self.assertEqual(rules["蓝色"]["target_layer"], "双点划线层")
        self.assertEqual(rules["洋红色"]["target_layer"], "细实线层")
        self.assertEqual(rules["白色+黑白色"]["target_layer"], "0层")
        for rule in rules.values():
            self.assertEqual(rule["target_color"], "ByLayer")
            self.assertEqual(rule["target_linetype"], "ByLayer")
            self.assertEqual(rule["linetype_scale"], 1.0)
            self.assertEqual(rule["target_lineweight"], "ByLayer")

    def test_excel_filename_is_part_of_the_exact_mapping(self):
        workbook = self.root / "names.xlsx"
        write_xlsx(workbook, self.workbook_rows())
        core.import_caxa_workbook_xlsx(self.db, workbook)
        other = self.source_dir / "CRB01D2084_另一个同图号文件.exb"
        other.write_bytes(b"other source")
        core.scan_folder(self.db, self.source_dir, exclude_dirs=())
        info = core.block_name_for_path(self.db, str(other))
        self.assertEqual(info["status"], "文件名与 Excel 映射不一致")
        self.assertEqual(info["block_name"], "")

    def test_explicit_source_color_column_overrides_confirmed_defaults(self):
        rows = [
            ["图号", "文件名", "块名称"],
            ["CRB01D2084", self.source1.name, "CRB01D2084_垂直重锤拉紧装置_B500_08轴_D500"],
            [None, None, None],
            ["线层", "线型", "线型比例", "线宽", "颜色", "原始颜色"],
            ["中心线层", "ByLayer", 1, "ByLayer", "ByLayer", "红色"],
            ["虚线层", "ByLayer", 1, "ByLayer", "ByLayer", "绿色"],
            ["双点划线层", "ByLayer", 1, "ByLayer", "ByLayer", "蓝色"],
            ["细实线层", "ByLayer", 1, "ByLayer", "ByLayer", "洋红色"],
            ["0层", "ByLayer", 1, "ByLayer", "ByLayer", "白色+黑白色"],
        ]
        workbook = self.root / "explicit-rules.xlsx"
        write_xlsx(workbook, rows)
        core.import_caxa_workbook_xlsx(self.db, workbook)
        rule = core.get_cad_color_rule(self.db, "白色 + 黑白色")
        self.assertEqual(rule["target_layer"], "0层")
        self.assertEqual(rule["target_color"], "ByLayer")

    def test_invalid_workbook_does_not_replace_existing_name_or_color_rules(self):
        valid = self.root / "valid.xlsx"
        write_xlsx(valid, self.workbook_rows())
        core.import_caxa_workbook_xlsx(self.db, valid)
        prior_name = core.block_name_for_path(self.db, str(self.source1))["block_name"]
        prior_rules = core.get_cad_color_rules(self.db)

        invalid_rows = self.workbook_rows()
        invalid_rows[2][0] = "CRB01D2084"
        invalid = self.root / "duplicate.xlsx"
        write_xlsx(invalid, invalid_rows)
        with self.assertRaisesRegex(ValueError, "图号重复"):
            core.import_caxa_workbook_xlsx(self.db, invalid)

        self.assertEqual(core.block_name_for_path(self.db, str(self.source1))["block_name"], prior_name)
        self.assertEqual(core.get_cad_color_rules(self.db), prior_rules)

    def test_legacy_two_column_name_workbook_remains_supported(self):
        workbook = self.root / "legacy.xlsx"
        write_xlsx(workbook, [
            ["图号", "正式块名称"],
            ["CRB01D2084", "CRB01D2084_垂直重锤拉紧装置_B500_08轴_D500"],
        ])
        self.assertEqual(core.import_block_names_xlsx(self.db, workbook), 1)
        self.assertEqual(core.block_name_for_path(self.db, str(self.source1))["status"], "已匹配")


if __name__ == "__main__":
    unittest.main(verbosity=2)
