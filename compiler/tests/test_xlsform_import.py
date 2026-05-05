from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.clinical_ir import ClinicalIRDocument
from chw_navigator.compare import compare_document_pair, load_patient_cases
from chw_navigator.validator import validate_document
from chw_navigator.xlsform_import import XLSFormImportError, import_xlsform_files, import_xlsform_files_detailed


EXAMPLES = ROOT / "examples"
GENERATED = ROOT / "generated"
TEST_ROOT = GENERATED / "test_artifacts" / "xlsform_import"
TEST_ROOT.mkdir(parents=True, exist_ok=True)


class XLSFormImportTests(unittest.TestCase):
    def test_imports_generated_pneumonia_workbook(self) -> None:
        imported = import_xlsform_files(
            str(GENERATED / "pneumonia" / "survey.csv"),
            str(GENERATED / "pneumonia" / "choices.csv"),
            guideline_id="pneumonia_imported",
        )
        self.assertEqual([], validate_document(imported))

        expected = _load_document(EXAMPLES / "pneumonia.ir.json")
        cases = load_patient_cases(str(EXAMPLES / "pneumonia.cases.json"))
        results = compare_document_pair(expected, imported, cases, label="imported xlsform")
        self.assertTrue(results)
        self.assertTrue(all(result.ok for result in results))

    def test_imports_generated_multi_module_workbook(self) -> None:
        imported = import_xlsform_files(
            str(GENERATED / "multi_module_router" / "survey.csv"),
            str(GENERATED / "multi_module_router" / "choices.csv"),
            guideline_id="multi_module_router_imported",
        )
        self.assertEqual([], validate_document(imported))

        expected = _load_document(EXAMPLES / "multi_module_router.ir.json")
        cases = load_patient_cases(str(EXAMPLES / "multi_module_router.cases.json"))
        results = compare_document_pair(expected, imported, cases, label="imported xlsform")
        self.assertTrue(results)
        self.assertTrue(all(result.ok for result in results))

    def test_imports_web_tip_example_with_standalone_output_calculation(self) -> None:
        imported = import_xlsform_files(
            str(EXAMPLES / "web_xlsform" / "tip_survey.csv"),
            str(EXAMPLES / "web_xlsform" / "tip_choices.csv"),
            guideline_id="tip_web_example",
        )
        self.assertEqual([], validate_document(imported))
        self.assertIn("o_tip", imported.outputs)
        self.assertIn("d_imported_calculations", imported.decisions)

    def test_normalizes_wild_xlsform_names_and_reports_findings(self) -> None:
        survey = TEST_ROOT / "wild_tip_survey.csv"
        choices = TEST_ROOT / "wild_tip_choices.csv"
        survey.write_text(
            "\n".join(
                [
                    "type,name,label,relevant,calculation,required,constraint",
                    '"decimal","amount","What was the price of the meal?","","","true()",""',
                    '"calculate","tip","","","${amount} * 0.18","",""',
                    '"note","display","18% tip for your meal is: ${tip}","${tip}","","",""',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        choices.write_text("list_name,name,label\n", encoding="utf-8")

        imported = import_xlsform_files_detailed(
            str(survey),
            str(choices),
            guideline_id="wild_tip_example",
        )

        self.assertIn("v_amount", imported.document.variables)
        self.assertIn("o_tip", imported.document.outputs)
        self.assertIn("d_imported_calculations", imported.document.decisions)
        self.assertEqual("v_amount", imported.report.name_map["amount"])
        self.assertEqual("o_tip", imported.report.name_map["tip"])
        statuses = {finding.status for finding in imported.report.findings}
        self.assertIn("normalized", statuses)
        self.assertIn("warning", statuses)

        expected = import_xlsform_files(
            str(EXAMPLES / "web_xlsform" / "tip_survey.csv"),
            str(EXAMPLES / "web_xlsform" / "tip_choices.csv"),
            guideline_id="tip_web_example",
        )
        results = compare_document_pair(
            expected,
            imported.document,
            load_patient_cases(str(EXAMPLES / "web_xlsform" / "tip_cases.json")),
            label="normalized wild xlsform",
        )
        self.assertTrue(results)
        self.assertTrue(all(result.ok for result in results))

    def test_rejects_name_collisions_after_normalization(self) -> None:
        survey = TEST_ROOT / "colliding_survey.csv"
        choices = TEST_ROOT / "colliding_choices.csv"
        survey.write_text(
            "\n".join(
                [
                    "type,name,label,relevant,calculation,required,constraint",
                    '"integer","age","Age","","","true()",""',
                    '"integer","v_age","Age 2","","","true()",""',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        choices.write_text("list_name,name,label\n", encoding="utf-8")

        with self.assertRaises(XLSFormImportError):
            import_xlsform_files_detailed(str(survey), str(choices), guideline_id="colliding")

    def test_rejects_question_relevant_logic_for_now(self) -> None:
        survey = TEST_ROOT / "bad_survey.csv"
        choices = TEST_ROOT / "bad_choices.csv"
        survey.write_text(
            "\n".join(
                [
                    "type,name,label,relevant,calculation,required,constraint",
                    '"select_one yes_no","v_has_fever","Fever?","${v_age_months} > 0","","true()",""',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        choices.write_text(
            "\n".join(
                [
                    "list_name,name,label",
                    '"yes_no","true","Yes"',
                    '"yes_no","false","No"',
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        with self.assertRaises(XLSFormImportError):
            import_xlsform_files(str(survey), str(choices), guideline_id="bad_relevant")


def _load_document(path: Path) -> ClinicalIRDocument:
    return ClinicalIRDocument.from_dict(json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
