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
from chw_navigator.validator import validate_document


EXAMPLES = ROOT / "examples"


class GoldenExampleTests(unittest.TestCase):
    def test_fever_basic_validates(self) -> None:
        document = _load_document(EXAMPLES / "fever_basic.ir.json")
        self.assertEqual([], validate_document(document))

    def test_fever_basic_matches_dmn_and_backends(self) -> None:
        document = _load_document(EXAMPLES / "fever_basic.ir.json")
        cases = load_patient_cases(str(EXAMPLES / "fever_basic.cases.json"))
        results = compare_backends(document, dmn_path=str(EXAMPLES / "fever_basic.dmn"), patient_cases=cases)
        self.assertTrue(results)
        self.assertTrue(all(result.ok for result in results))


def _load_document(path: Path) -> ClinicalIRDocument:
    return ClinicalIRDocument.from_dict(json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
