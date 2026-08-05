from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FIXTURE = ROOT / "contracts" / "examples" / "tracer" / "valid-registry-set.json"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.diagnostics import DiagnosticCode
from chw_navigator.registry_set import parse_registry_set, validate_release1_subject_scope


class SubjectScopeTests(unittest.TestCase):
    def test_release1_accepts_current_contact(self) -> None:
        document = parse_registry_set(json.loads(FIXTURE.read_text(encoding="utf-8")))
        self.assertEqual("current_contact", document.capability_registry.capabilities[0].subject_scope)
        self.assertEqual((), validate_release1_subject_scope("current_contact"))

    def test_every_group_scope_requires_a_separate_obligation_model(self) -> None:
        for scope in ("household", "service_area", "cohort"):
            with self.subTest(scope=scope):
                diagnostics = validate_release1_subject_scope(scope)
                self.assertEqual(1, len(diagnostics))
                self.assertEqual(DiagnosticCode.SUBJECT_SCOPE_GROUP_UNSUPPORTED, diagnostics[0].code)
                self.assertIn("separate group-obligation model", diagnostics[0].message)

    def test_unknown_scope_is_a_schema_error(self) -> None:
        diagnostics = validate_release1_subject_scope("facility")
        self.assertEqual(DiagnosticCode.REGISTRY_SCHEMA_INVALID, diagnostics[0].code)


if __name__ == "__main__":
    unittest.main()
