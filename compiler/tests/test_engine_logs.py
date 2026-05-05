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
from chw_navigator.compare import build_comparison_log, build_z3_checks_log, compare_backends, load_patient_cases
from chw_navigator.z3_backend import analyze_document


EXAMPLES = ROOT / "examples"


class EngineLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = ClinicalIRDocument.from_dict(json.loads((EXAMPLES / "pneumonia.ir.json").read_text(encoding="utf-8")))
        self.cases = load_patient_cases(str(EXAMPLES / "pneumonia.cases.json"))

    def test_comparison_log_matches_contract_shape(self) -> None:
        results = compare_backends(self.document, dmn_path=str(EXAMPLES / "pneumonia.dmn"), patient_cases=self.cases)
        log = build_comparison_log(
            guideline_id=self.document.metadata.guideline_id,
            results=results,
            source_artifacts={"ir_path": "examples/pneumonia.ir.json"},
        )
        self.assertEqual("comparison_report", log["log_type"])
        self.assertEqual(1, log["contract_version"])
        self.assertEqual(self.document.metadata.guideline_id, log["guideline_id"])
        self.assertEqual("examples/pneumonia.ir.json", log["source_artifacts"]["ir_path"])
        self.assertTrue(log["results"])
        first = log["results"][0]
        self.assertIn("category", first)
        self.assertIn("tags", first)
        self.assertIn("interpreter_outputs", first)
        self.assertIn("mermaid_ok", first)
        self.assertIn("mermaid_trace_nodes", first)
        self.assertIn("mismatches", first)
        self.assertIsInstance(first["mismatches"], list)

    def test_z3_checks_log_matches_contract_shape(self) -> None:
        report = analyze_document(self.document)
        log = build_z3_checks_log(guideline_id=self.document.metadata.guideline_id, report=report)
        self.assertEqual("z3_checks", log["log_type"])
        self.assertEqual(1, log["contract_version"])
        self.assertEqual(self.document.metadata.guideline_id, log["guideline_id"])
        self.assertTrue(log["results"])
        first = log["results"][0]
        self.assertIn("category", first)
        self.assertIn("target", first)
        self.assertIn("ok", first)
        self.assertIn("message", first)


if __name__ == "__main__":
    unittest.main()
