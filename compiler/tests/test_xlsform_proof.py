from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.cli import main as cli_main
from chw_navigator.clinical_ir import ClinicalIRDocument
from chw_navigator.compare import load_patient_cases
from chw_navigator.xlsform_proof import build_xlsform_roundtrip_proof
from test_support import create_test_run, reset_suite_runs


EXAMPLES = ROOT / "examples"
GENERATED = ROOT / "generated"


class XLSFormProofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_suite_runs("xlsform_proof")

    def setUp(self) -> None:
        self.test_run = create_test_run(
            suite_name="xlsform_proof",
            test_name=self.id().split(".")[-1],
            purpose="Round-trip XLSForm proof tests for supported importer subsets.",
            input_paths=(
                GENERATED / "pneumonia" / "survey.csv",
                GENERATED / "pneumonia" / "choices.csv",
                EXAMPLES / "pneumonia.ir.json",
                EXAMPLES / "pneumonia.cases.json",
            ),
        )

    def test_builds_roundtrip_proof_against_reference_ir(self) -> None:
        reference = ClinicalIRDocument.from_dict(json.loads((EXAMPLES / "pneumonia.ir.json").read_text(encoding="utf-8")))
        cases = load_patient_cases(str(EXAMPLES / "pneumonia.cases.json"))
        built = build_xlsform_roundtrip_proof(
            survey_path=GENERATED / "pneumonia" / "survey.csv",
            choices_path=GENERATED / "pneumonia" / "choices.csv",
            output_dir=self.test_run.outputs_dir / "proof",
            guideline_id="pneumonia_roundtrip",
            reference_document=reference,
            patient_cases=cases,
        )
        self.assertTrue(built.imported_ir_path.exists())
        self.assertTrue(built.summary_path.exists())
        workbook_pairwise = json.loads(built.workbook_pairwise_report_path.read_text(encoding="utf-8"))
        backend_compare = json.loads(built.backend_compare_path.read_text(encoding="utf-8"))
        reference_pairwise = json.loads(built.reference_equivalence_report_path.read_text(encoding="utf-8"))
        self.assertTrue(workbook_pairwise["equivalent_on_case_suite"])
        self.assertTrue(reference_pairwise["equivalent_on_case_suite"])
        self.assertTrue(all(item["ok"] for item in backend_compare["results"]))

    def test_cli_prove_xlsform_succeeds_for_tip_example(self) -> None:
        output_dir = self.test_run.outputs_dir / "cli_tip_proof"
        exit_code = cli_main(
            [
                "prove-xlsform",
                str(EXAMPLES / "web_xlsform" / "tip_survey.csv"),
                str(EXAMPLES / "web_xlsform" / "tip_choices.csv"),
                str(output_dir),
                "--patients",
                str(EXAMPLES / "web_xlsform" / "tip_cases.json"),
            ]
        )
        self.assertEqual(0, exit_code)
        self.assertTrue((output_dir / "proof_summary.md").exists())
        workbook_pairwise = json.loads((output_dir / "workbook_pairwise.compare.json").read_text(encoding="utf-8"))
        self.assertTrue(workbook_pairwise["equivalent_on_case_suite"])


if __name__ == "__main__":
    unittest.main()
