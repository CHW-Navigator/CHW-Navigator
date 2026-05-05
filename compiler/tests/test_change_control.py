from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
EXAMPLES = ROOT / "examples"
TEST_ROOT = ROOT / "generated" / "test_artifacts" / "change_control"
TEST_ROOT.mkdir(parents=True, exist_ok=True)

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.change_control import create_change_review_package, load_change_memo
from chw_navigator.clinical_ir import ClinicalIRDocument
from chw_navigator.lint import lint_document
from chw_navigator.validator import validate_document


class ChangeControlTests(unittest.TestCase):
    def test_change_review_package_builds_for_example_delta(self) -> None:
        memo = load_change_memo(EXAMPLES / "change_memos" / "pneumonia_covid_no_test.memo.json")
        baseline = _load_document(EXAMPLES / "pneumonia.ir.json")
        updated = _load_document(EXAMPLES / "pneumonia_covid_no_test.ir.json")

        self.assertEqual([], validate_document(updated))
        self.assertEqual([], lint_document(updated))

        built = create_change_review_package(
            memo=memo,
            baseline_document=baseline,
            updated_document=updated,
            review_root=TEST_ROOT,
            baseline_ir_path=EXAMPLES / "pneumonia.ir.json",
            updated_ir_path=EXAMPLES / "pneumonia_covid_no_test.ir.json",
            patient_cases_path=EXAMPLES / "pneumonia_covid_no_test.cases.json",
        )

        self.assertTrue(built.review_dir.exists())
        self.assertTrue(built.summary_path.exists())
        self.assertTrue(built.semantic_diff_path.exists())
        self.assertTrue(built.xlsform_diff_path.exists())
        self.assertTrue(built.impact_map_path.exists())
        self.assertTrue(built.workflow_burden_path.exists())
        self.assertTrue((built.review_dir / "tests" / "validation" / "safety_report.json").exists())
        self.assertTrue((built.review_dir / "tests" / "validation" / "validation_report.json").exists())
        self.assertTrue((built.review_dir / "outputs" / "baseline_cht" / "cht_lowering_plan.json").exists())
        self.assertTrue((built.review_dir / "outputs" / "updated_cht" / "cht_lowering_plan.json").exists())
        self.assertIsNotNone(built.case_delta_path)
        self.assertTrue(built.case_delta_path is not None and built.case_delta_path.exists())

        semantic_diff = json.loads(built.semantic_diff_path.read_text(encoding="utf-8"))
        self.assertEqual(1, semantic_diff["variables"]["counts"]["added"])
        self.assertEqual(1, semantic_diff["outputs"]["counts"]["added"])
        impact_map = json.loads(built.impact_map_path.read_text(encoding="utf-8"))
        self.assertTrue(impact_map["changed_predicates"])
        workflow_burden = json.loads(built.workflow_burden_path.read_text(encoding="utf-8"))
        self.assertIn("delta", workflow_burden)

        case_delta = json.loads(built.case_delta_path.read_text(encoding="utf-8"))  # type: ignore[arg-type]
        self.assertEqual(4, case_delta["counts"]["total_cases"])
        self.assertEqual(1, case_delta["counts"]["changed_cases"])

        summary_text = built.summary_path.read_text(encoding="utf-8")
        self.assertIn("pneumonia-covid-no-test-v1", summary_text)
        self.assertIn("Changed explicit patient cases: `1` of `4`", summary_text)
        self.assertIn("Workflow Burden", summary_text)

        readme_text = built.readme_path.read_text(encoding="utf-8")
        self.assertIn("Compiler version:", readme_text)
        self.assertIn("Purpose of the tests", readme_text)
        self.assertIn("impact_map.md", readme_text)


def _load_document(path: Path) -> ClinicalIRDocument:
    return ClinicalIRDocument.from_dict(json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
