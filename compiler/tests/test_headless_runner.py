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
from chw_navigator.compare import compare_backends, load_patient_cases
from chw_navigator.headless_runner import evaluate_workbook_headless
from chw_navigator.xlsform_backend import build_xlsform
from chw_navigator.xlsform_runtime import evaluate_workbook


EXAMPLES = ROOT / "examples"


class HeadlessRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = ClinicalIRDocument.from_dict(json.loads((EXAMPLES / "pneumonia.ir.json").read_text(encoding="utf-8")))
        self.cases = load_patient_cases(str(EXAMPLES / "pneumonia.cases.json"))
        self.workbook = build_xlsform(self.document).workbook

    def test_headless_runner_matches_generated_runtime(self) -> None:
        for case in self.cases:
            patient_values = {
                key: value for key, value in case.values.items() if key not in case.missing
            }
            runtime_result = evaluate_workbook(self.workbook, patient_values)
            headless_result = evaluate_workbook_headless(self.workbook, patient_values)
            self.assertEqual(runtime_result.values, headless_result.values)
            self.assertEqual(runtime_result.visible_notes, headless_result.visible_notes)

    def test_compare_backends_includes_headless_outputs(self) -> None:
        results = compare_backends(
            self.document,
            dmn_path=str(EXAMPLES / "pneumonia.dmn"),
            patient_cases=self.cases,
        )
        self.assertTrue(results)
        self.assertTrue(all(result.ok for result in results))
        first = results[0]
        self.assertIn("p_danger_sign", first.headless_predicates)
        self.assertIn("o_referral", first.headless_outputs)
        self.assertIn("r1", first.headless_rule_hits)


if __name__ == "__main__":
    unittest.main()
