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
from chw_navigator.compare import compare_backends
from chw_navigator.z3_backend import generate_test_patients


EXAMPLES = ROOT / "examples"


class Z3PatientSuiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router_document = _load_document(EXAMPLES / "multi_module_router.ir.json")

    def test_generates_required_case_categories(self) -> None:
        cases = generate_test_patients(self.router_document)
        categories = [case.category for case in cases]

        self.assertIn("endpoint", categories)
        self.assertIn("pairwise_modules", categories)
        self.assertIn("cutpoint", categories)
        self.assertIn("no_problems", categories)
        self.assertEqual(5, sum(1 for case in cases if case.category == "repeatability"))

    def test_generates_expected_pairwise_and_cutpoint_examples(self) -> None:
        cases = generate_test_patients(self.router_document)

        self.assertTrue(any(case.name == "pair_cough_fever" for case in cases))
        self.assertTrue(any(case.name == "pair_cough_diarrhea" for case in cases))
        self.assertTrue(any(case.name == "cutpoint_v_fever_days_2" for case in cases))
        self.assertTrue(any(case.name == "cutpoint_v_fever_days_3" for case in cases))
        self.assertTrue(any(case.name == "cutpoint_v_fever_days_4" for case in cases))
        no_problem = next(case for case in cases if case.category == "no_problems")
        self.assertFalse(no_problem.values["v_has_danger_sign"])
        self.assertFalse(no_problem.values["v_has_fever"])
        self.assertFalse(no_problem.values["v_has_cough"])
        self.assertFalse(no_problem.values["v_has_diarrhea"])

    def test_compare_backends_uses_z3_derived_suite(self) -> None:
        results = compare_backends(self.router_document, dmn_path=str(EXAMPLES / "multi_module_router.dmn"))

        self.assertTrue(results)
        self.assertTrue(any(result.category == "pairwise_modules" for result in results))
        self.assertTrue(any(result.category == "cutpoint" for result in results))
        self.assertTrue(any(result.category == "no_problems" for result in results))
        self.assertEqual(5, sum(1 for result in results if result.category == "repeatability"))
        self.assertTrue(all(result.ok for result in results))
        self.assertTrue(all(result.mermaid_ok for result in results))


def _load_document(path: Path) -> ClinicalIRDocument:
    return ClinicalIRDocument.from_dict(json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
