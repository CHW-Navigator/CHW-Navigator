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


class MultiModuleRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = _load_document(EXAMPLES / "multi_module_router.ir.json")
        self.cases = load_patient_cases(str(EXAMPLES / "multi_module_router.cases.json"))

    def test_multi_module_router_validates(self) -> None:
        errors = validate_document(self.document)
        self.assertEqual([], errors)

    def test_multi_module_router_matches_dmn(self) -> None:
        results = compare_backends(
            self.document,
            dmn_path=str(EXAMPLES / "multi_module_router.dmn"),
            patient_cases=self.cases,
        )
        self.assertTrue(results)
        self.assertTrue(all(result.ok for result in results))


def _load_document(path: Path) -> ClinicalIRDocument:
    return ClinicalIRDocument.from_dict(json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
