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


def inline_cell(reference, value):
    return f'<c r="{reference}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'


def shared_cell(reference, index):
    return f'<c r="{reference}" t="s"><v>{index}</v></c>'


def write_xlsx(path, rows, *, shared=False):
    row_xml = []
    shared_values = []
    for row_number, values in enumerate(rows, 1):
        cells = []
        for column, value in enumerate(values, 1):
            reference = ("A" if column == 1 else "B" if column == 2 else "C") + str(row_number)
            if shared:
                if value not in shared_values:
                    shared_values.append(value)
                cells.append(shared_cell(reference, shared_values.index(value)))
            else:
                cells.append(inline_cell(reference, value))
        row_xml.append(f'<row r="{row_number}">{"".join(cells)}</row>')

    worksheet = f'<worksheet xmlns="{MAIN_NS}"><sheetData>{"".join(row_xml)}</sheetData></worksheet>'
    workbook = (
        f'<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}">'
        '<sheets><sheet name="Names" sheetId="1" r:id="rId1"/></sheets></workbook>'
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
        if shared:
            strings = "".join(f"<si><t>{escape(value)}</t></si>" for value in shared_values)
            archive.writestr(
                "xl/sharedStrings.xml",
                f'<sst xmlns="{MAIN_NS}" count="{len(shared_values)}" uniqueCount="{len(shared_values)}">{strings}</sst>',
            )


class ExcelBlockNameImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source_dir = self.root / "source"
        self.source_dir.mkdir()
        self.source = self.source_dir / "CRB01D2084_垂直重锤拉紧装置.exb"
        self.source.write_bytes(b"synthetic test EXB bytes")
        self.db = core.connect(self.root / "progress.sqlite3")
        core.scan_folder(self.db, self.source_dir, exclude_dirs=())

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_imports_two_column_xlsx_and_matches_exact_code(self):
        workbook = self.root / "names.xlsx"
        write_xlsx(workbook, [
            ["图号", "正式块名称"],
            ["CRB01D2084", "CRB01D2084_垂直重锤拉紧装置_B500_08轴_D500"],
        ])
        self.assertEqual(core.import_block_names_xlsx(self.db, workbook), 1)
        info = core.block_name_for_path(self.db, str(self.source))
        self.assertEqual(info["status"], "已匹配")
        self.assertEqual(
            info["block_name"],
            "CRB01D2084_垂直重锤拉紧装置_B500_08轴_D500",
        )

    def test_shared_string_workbook_is_supported(self):
        workbook = self.root / "shared.xlsx"
        write_xlsx(workbook, [
            ["图号", "正式块名称"],
            ["CRB01D2084", "CRB01D2084_垂直重锤拉紧装置_B500_08轴_D500"],
        ], shared=True)
        self.assertEqual(core.import_block_names_xlsx(self.db, workbook), 1)

    def test_duplicate_code_is_reported_and_previous_mapping_is_preserved(self):
        valid = self.root / "valid.xlsx"
        write_xlsx(valid, [
            ["图号", "正式块名称"],
            ["CRB01D2084", "CRB01D2084_垂直重锤拉紧装置_B500_08轴_D500"],
        ])
        core.import_block_names_xlsx(self.db, valid)

        duplicate = self.root / "duplicate.xlsx"
        write_xlsx(duplicate, [
            ["图号", "正式块名称"],
            ["CRB01D2084", "CRB01D2084_名称一"],
            ["CRB01D2084", "CRB01D2084_名称二"],
        ])
        with self.assertRaisesRegex(ValueError, "图号重复"):
            core.import_block_names_xlsx(self.db, duplicate)
        info = core.block_name_for_path(self.db, str(self.source))
        self.assertEqual(info["block_name"], "CRB01D2084_垂直重锤拉紧装置_B500_08轴_D500")

    def test_code_and_block_name_prefix_must_agree(self):
        workbook = self.root / "mismatch.xlsx"
        write_xlsx(workbook, [
            ["图号", "正式块名称"],
            ["CRB01D2084", "CRB01D2085_垂直重锤拉紧装置_B500_08轴_D500"],
        ])
        with self.assertRaisesRegex(ValueError, "前缀不一致"):
            core.import_block_names_xlsx(self.db, workbook)

    def test_only_two_nonempty_columns_are_accepted(self):
        workbook = self.root / "three-columns.xlsx"
        write_xlsx(workbook, [
            ["图号", "正式块名称", "备注"],
            ["CRB01D2084", "CRB01D2084_垂直重锤拉紧装置_B500_08轴_D500", "额外内容"],
        ])
        with self.assertRaisesRegex(ValueError, "未定义的图纸映射列"):
            core.import_block_names_xlsx(self.db, workbook)


if __name__ == "__main__":
    unittest.main(verbosity=2)
