from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.clinical_ir import ClinicalIRDocument
from chw_navigator.form_ir import SurveyRow, XLSFormWorkbook
from chw_navigator.xlsform_runtime import XLSFormRuntimeError, evaluate_workbook
from chw_navigator.z3_backend import Z3BackendUnavailable, analyze_document


class RuntimeHardeningTests(unittest.TestCase):
    def test_xlsform_runtime_wraps_division_by_zero(self) -> None:
        workbook = XLSFormWorkbook(
            title="division_zero",
            form_id="division_zero",
            survey=[
                SurveyRow(type="integer", name="v_num", label="v_num"),
                SurveyRow(type="integer", name="v_den", label="v_den"),
                SurveyRow(type="calculate", name="calc_ratio", calculation="${v_num} / ${v_den}"),
            ],
        )

        with self.assertRaises(XLSFormRuntimeError) as ctx:
            evaluate_workbook(workbook, {"v_num": 4, "v_den": 0})
        self.assertIn("division by zero", str(ctx.exception))

    def test_z3_analysis_raises_custom_unavailable_error(self) -> None:
        document = ClinicalIRDocument.from_dict(
            {
                "metadata": {
                    "ir_version": 1,
                    "guideline_id": "z3_unavailable",
                    "sources": [{"id": "test", "kind": "manual", "ref": "test"}],
                },
                "variables": {},
                "predicates": {},
                "outputs": {},
                "decisions": {},
                "invariants": {},
                "phrase_bindings": {},
            }
        )

        with patch("chw_navigator.z3_backend.z3", None):
            with self.assertRaises(Z3BackendUnavailable):
                analyze_document(document)


if __name__ == "__main__":
    unittest.main()
