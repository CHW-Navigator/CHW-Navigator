from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.clinical_vocabulary import (
    CLINICAL_VOCABULARY_VERSION,
    ClinicalDerivationError,
    clinical_object_findings,
    contains_clinical_derivation,
    contains_clinical_vocabulary,
    reject_clinical_derivation,
)
from chw_navigator.diagnostics import DiagnosticCode


class ClinicalVocabularyTests(unittest.TestCase):
    def test_version_and_renamed_clinical_terms_are_shared(self) -> None:
        self.assertEqual("1.0.0", CLINICAL_VOCABULARY_VERSION)
        for value in (
            "deriveDiagnosis(age >= 2)",
            "derive_diagnosis(age >= 2)",
            "dx_severe_pneumonia",
            "recommend-treatment when spo2 < 90",
            "fastBreathing && rr >= 50",
        ):
            self.assertTrue(contains_clinical_derivation(value), value)
        self.assertTrue(contains_clinical_vocabulary("treatmentRecommendation"))

    def test_nested_keys_and_fhir_resources_fail_closed(self) -> None:
        value = {
            "safe": [
                {"clinicalDecision": "renamed"},
                {"resourceType": "MedicationRequest"},
                {"code": "return { diagnosis: value };"},
            ]
        }
        self.assertEqual(
            (
                "safe[0].clinicalDecision",
                "safe[1].resourceType",
                "safe[2].code",
            ),
            clinical_object_findings(value),
        )
        with self.assertRaises(ClinicalDerivationError) as raised:
            reject_clinical_derivation(value, context="extension library")
        self.assertEqual(DiagnosticCode.CLINICAL_DERIVATION_FORBIDDEN, raised.exception.code)
        self.assertIn(DiagnosticCode.CLINICAL_DERIVATION_FORBIDDEN, str(raised.exception))

    def test_technical_calendar_computation_is_not_clinical_derivation(self) -> None:
        value = {
            "function": "calculateGestationalAge",
            "code": "const elapsedDays = (asOf - lmp) / DAY_MS; return response('ok', elapsedDays);",
        }
        self.assertEqual((), clinical_object_findings(value))


if __name__ == "__main__":
    unittest.main()
