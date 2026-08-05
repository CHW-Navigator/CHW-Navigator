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

from chw_navigator.clinical_ir import ClinicalIRDocument
from chw_navigator.compare import compare_backends, load_patient_cases


class ExternalPatientSuiteTests(unittest.TestCase):
    def test_external_review_suite_matches_all_engines_for_pneumonia(self) -> None:
        document = ClinicalIRDocument.from_dict(
            json.loads((EXAMPLES / "pneumonia.ir.json").read_text(encoding="utf-8"))
        )
        cases = load_patient_cases(str(EXAMPLES / "external_suites" / "pneumonia_external_review_cases.json"))
        results = compare_backends(document, dmn_path=str(EXAMPLES / "pneumonia.dmn"), patient_cases=cases)
        self.assertTrue(results)
        self.assertTrue(all(result.ok for result in results))
        self.assertTrue(all("external_designed" in result.tags for result in results))


if __name__ == "__main__":
    unittest.main()
