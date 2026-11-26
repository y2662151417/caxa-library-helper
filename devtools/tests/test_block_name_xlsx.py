import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import core


MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def write_test_workbook(path):
    workbook = (
        f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>'
        '<sheet name="Sheet1" sheetId="1" r:id="rId1"/>'
        '</sheets></workbook>'
    )
    relationships = (
        f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    shared = (
        f'<sst xmlns="{MAIN}" count="4" uniqueCount="4">'
        '<si><t>图号</t></si><si><t>块名称</t></si>'
        '<si><t>CRB01D2084</t></si>'
        '<si><t>CRB01D2084_垂直重锤拉紧装置_B500_08轴_D500</t></si>'
        '</sst>'
    )
    sheet = (
        f'<worksheet xmlns="{MAIN}"><sheetData>'
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
        '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2" t="s"><v>3</v></c></row>'
        '</sheetData></worksheet>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/sharedStrings.xml", shared)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


class BlockNameXlsxTests(unittest.TestCase):
    def test_reads_two_column_mapping_and_imports_it(self):
        with tempfile.TemporaryDirectory() as temp:
            xlsx = Path(temp) / "正式块名称.xlsx"
            write_test_workbook(xlsx)
            self.assertEqual(
                core.read_block_names_xlsx(xlsx),
                [
                    ["图号", "块名称"],
                    ["CRB01D2084", "CRB01D2084_垂直重锤拉紧装置_B500_08轴_D500"],
                ],
            )
            db = core.connect(Path(temp) / "test.sqlite3")
            try:
                self.assertEqual(core.import_block_names_xlsx(db, xlsx), 1)
                rows = core.block_name_summary(db)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["code"], "CRB01D2084")
                self.assertEqual(
                    rows[0]["block_name"],
                    "CRB01D2084_垂直重锤拉紧装置_B500_08轴_D500",
                )
            finally:
                db.close()

    def test_rejects_non_xlsx_and_invalid_workbook(self):
        with tempfile.TemporaryDirectory() as temp:
            text_file = Path(temp) / "names.csv"
            text_file.write_text("图号,块名称\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                core.read_block_names_xlsx(text_file)
            broken = Path(temp) / "broken.xlsx"
            broken.write_bytes(b"not a zip")
            with self.assertRaises(ValueError):
                core.read_block_names_xlsx(broken)


if __name__ == "__main__":
    unittest.main(verbosity=2)
