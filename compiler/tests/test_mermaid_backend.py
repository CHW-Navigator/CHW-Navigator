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
from chw_navigator.mermaid_backend import MermaidOptions, build_mermaid_artifact


EXAMPLES = ROOT / "examples"


class MermaidBackendTests(unittest.TestCase):
    def test_build_mermaid_uses_readable_defaults(self) -> None:
        document = _load_document(EXAMPLES / "pneumonia.ir.json")

        artifact = build_mermaid_artifact(document)

        self.assertIn("flowchart LR", artifact.text)
        self.assertIn("classDef variable", artifact.text)
        self.assertIn("classDef output", artifact.text)
        self.assertIn('"Age months"', artifact.text)
        self.assertIn('"Danger sign"', artifact.text)
        self.assertIn('"Triage"', artifact.text)
        self.assertIn('"Home treatment"', artifact.text)
        self.assertIn('"R2: Fast breathing and<br/>not(Danger sign)"', artifact.text)

    def test_build_mermaid_respects_direction_and_font_size(self) -> None:
        document = _load_document(EXAMPLES / "pneumonia.ir.json")

        artifact = build_mermaid_artifact(document, options=MermaidOptions(direction="TD", font_size_px=30))

        self.assertIn("flowchart TD", artifact.text)
        self.assertIn('"fontSize":"30px"', artifact.text)
        self.assertIn("font-size:30px", artifact.text)


def _load_document(path: Path) -> ClinicalIRDocument:
    return ClinicalIRDocument.from_dict(json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
