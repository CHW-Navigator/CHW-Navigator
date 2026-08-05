from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.clinical_ir import ClinicalIRDocument
from chw_navigator.compare import (
    ComparisonCase,
    ComparisonError,
    compare_backends,
    compare_document_pair,
    compare_workbook_pair,
    load_patient_cases,
)
from chw_navigator.form_ir import load_xlsform_workbook
from chw_navigator.mermaid_backend import build_mermaid_artifact, compare_mermaid_text
from chw_navigator.xlsform_backend import build_xlsform, write_xlsform_csvs
from chw_navigator.z3_backend import compare_smt2_file, export_smt2
from test_support import create_test_run, reset_suite_runs


EXAMPLES = ROOT / "examples"


class ArtifactDriftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_suite_runs("artifact_drift")

    def setUp(self) -> None:
        self.document = _load_document(EXAMPLES / "pneumonia.ir.json")
        self.cases = load_patient_cases(str(EXAMPLES / "pneumonia.cases.json"))
        self.good_dmn = (EXAMPLES / "pneumonia.dmn").read_text(encoding="utf-8")
        self.test_run = create_test_run(
            suite_name="artifact_drift",
            test_name=self.id().split(".")[-1],
            purpose="Mutation and drift checks for DMN, XLSForm, Mermaid, IR, and SMT-LIB artifacts.",
            input_paths=(EXAMPLES / "pneumonia.ir.json", EXAMPLES / "pneumonia.dmn", EXAMPLES / "pneumonia.cases.json"),
        )

    def test_mutated_dmn_is_detected(self) -> None:
        mutated = self.good_dmn.replace(
            '<outputEntry id="r2_o2"><text>true</text></outputEntry>',
            '<outputEntry id="r2_o2"><text>false</text></outputEntry>',
        )
        dmn_path = self.test_run.outputs_dir / "mutated_outcome.dmn"
        dmn_path.write_text(mutated, encoding="utf-8")
        results = compare_backends(self.document, dmn_path=str(dmn_path), patient_cases=self.cases)

        self.assertTrue(any(not result.ok for result in results))
        mismatch_text = "\n".join(
            mismatch
            for result in results
            for mismatch in result.mismatches
        )
        self.assertIn("DMN outputs mismatch", mismatch_text)

    def test_z3_generated_cases_match_across_backends(self) -> None:
        results = compare_backends(self.document, dmn_path=str(EXAMPLES / "pneumonia.dmn"))
        self.assertTrue(results)
        self.assertTrue(all(result.ok for result in results))

    def test_mutated_xlsform_is_detected(self) -> None:
        built = build_xlsform(self.document)
        output_dir = self.test_run.outputs_dir / "mutated_xlsform"
        survey_path, choices_path, _ = write_xlsform_csvs(built, str(output_dir))
        survey_text = Path(survey_path).read_text(encoding="utf-8")
        survey_text = survey_text.replace(
            '"calculate","state__o_home_treatment__d_triage","","","if(${rh_r2}, true(), false())","",""',
            '"calculate","state__o_home_treatment__d_triage","","","if(${rh_r2}, false(), false())","",""',
        )
        Path(survey_path).write_text(survey_text + ("" if survey_text.endswith("\n") else "\n"), encoding="utf-8")
        workbook = load_xlsform_workbook(survey_path, choices_path)

        results = compare_workbook_pair(self.document, workbook, self.cases, label="mutated workbook")
        self.assertTrue(any(not result.ok for result in results))
        self.assertTrue(
            any("mutated workbook outputs mismatch" in mismatch for result in results for mismatch in result.mismatches)
        )

    def test_exported_smt2_matches_reference(self) -> None:
        smt2_path = self.test_run.outputs_dir / "pneumonia.smt2"
        smt2_path.write_text(export_smt2(self.document), encoding="utf-8")
        results = compare_smt2_file(self.document, str(smt2_path), self.cases)
        self.assertTrue(results)
        self.assertTrue(all(result.ok for result in results))

    def test_mutated_mermaid_is_detected(self) -> None:
        artifact = build_mermaid_artifact(self.document)
        mutated_text = artifact.text.replace(
            'd_triage__r2 -->|o_home_treatment=true| o_home_treatment',
            'd_triage__r2 -->|o_home_treatment=false| o_home_treatment',
        )
        comparison = compare_mermaid_text(self.document, mutated_text)
        self.assertFalse(comparison.ok)
        self.assertTrue(any("unexpected mermaid line" in item for item in comparison.mismatches))
        self.assertTrue(any("missing mermaid line" in item for item in comparison.mismatches))

    def test_mutated_ir_is_detected(self) -> None:
        mutated = copy.deepcopy(self.document)
        mutated.decisions["d_triage"].rules[1].then["o_home_treatment"] = False
        results = compare_document_pair(self.document, mutated, self.cases, label="mutated IR")
        self.assertTrue(any(not result.ok for result in results))
        self.assertTrue(any("mutated IR outputs mismatch" in item for result in results for item in result.mismatches))

    def test_compare_rejects_none_for_present_boolean_inputs(self) -> None:
        bad_case = ComparisonCase(
            name="bad_none_case",
            values={"v_age_months": 12, "v_resp_rate": 40, "v_danger_sign": None},
        )
        with self.assertRaises(ComparisonError):
            compare_backends(self.document, dmn_path=str(EXAMPLES / "pneumonia.dmn"), patient_cases=[bad_case])

    def test_mutated_smt2_is_detected(self) -> None:
        smt2_text = export_smt2(self.document)
        mutated_text = smt2_text.replace(
            "(assert\n (= o_home_treatment (ite r2 true false)))",
            "(assert\n (= o_home_treatment (ite r2 false false)))",
        )
        smt2_path = self.test_run.outputs_dir / "mutated_pneumonia.smt2"
        smt2_path.write_text(mutated_text, encoding="utf-8")
        results = compare_smt2_file(self.document, str(smt2_path), self.cases, label="mutated SMT-LIB")
        self.assertTrue(any(not result.ok for result in results))
        self.assertTrue(any("mutated SMT-LIB outputs mismatch" in item for result in results for item in result.mismatches))


def _load_document(path: Path) -> ClinicalIRDocument:
    return ClinicalIRDocument.from_dict(json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
