from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
EXAMPLES = ROOT / "examples"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.catalogs import compose_document_from_catalogs
from chw_navigator.cli import main as cli_main
from chw_navigator.compare import load_patient_cases
from chw_navigator.dmn import import_dmn_decisions
from chw_navigator.equivalence import build_case_suite_equivalence_report


class EquivalenceReportTests(unittest.TestCase):
    def test_case_suite_equivalence_report_detects_cutoff_shift_difference(self) -> None:
        baseline = _compose_pneumonia_document(EXAMPLES / "catalogs" / "pneumonia.predicates.json")
        candidate = _compose_pneumonia_document(EXAMPLES / "catalogs" / "pneumonia_rr_cutoff_plus1.predicates.json")
        cases = load_patient_cases(str(EXAMPLES / "pneumonia_rr_cutoff_plus1.cases.json"))
        output_dir = ROOT / "generated" / "t" / "equivalence_manual"
        built = build_case_suite_equivalence_report(
            baseline_document=baseline,
            candidate_document=candidate,
            patient_cases=cases,
            output_dir=output_dir,
            baseline_label="pneumonia",
            candidate_label="pneumonia_rr_cutoff_plus1",
        )
        report = json.loads(built.report_path.read_text(encoding="utf-8"))
        self.assertFalse(report["equivalent_on_case_suite"])
        self.assertFalse(report["equivalent_outputs_on_case_suite"])
        self.assertEqual(2, report["changed_case_count"])
        self.assertEqual(1, report["output_changed_case_count"])
        self.assertTrue(any(not item["ok"] for item in report["results"]))

    def test_equivalence_report_cli_succeeds_for_identical_documents(self) -> None:
        output_dir = ROOT / "generated" / "t" / "equivalence_cli"
        exit_code = cli_main(
            [
                "build-equivalence-report",
                str(EXAMPLES / "fever_basic.ir.json"),
                str(EXAMPLES / "fever_basic.ir.json"),
                str(EXAMPLES / "fever_basic.cases.json"),
                str(output_dir),
            ]
        )
        self.assertEqual(0, exit_code)
        report = json.loads((output_dir / "equivalence_report.json").read_text(encoding="utf-8"))
        self.assertTrue(report["equivalent_on_case_suite"])
        self.assertTrue(report["equivalent_outputs_on_case_suite"])


def _compose_pneumonia_document(predicate_path: Path):
    base = compose_document_from_catalogs(
        EXAMPLES / "catalogs" / "pneumonia.metadata.json",
        EXAMPLES / "catalogs" / "pneumonia.variables.csv",
        predicate_path,
        EXAMPLES / "catalogs" / "pneumonia.phrases.csv",
    )
    return import_dmn_decisions(base, str(EXAMPLES / "pneumonia.dmn"))


if __name__ == "__main__":
    unittest.main()
