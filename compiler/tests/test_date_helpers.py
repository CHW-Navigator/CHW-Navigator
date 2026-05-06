from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.clinical_ir import ClinicalIRDocument, MissingnessPolicy
from chw_navigator.compare import ComparisonCase, compare_backends, compare_document_pair
from chw_navigator.evaluator import evaluate_document
from chw_navigator.xlsform_backend import build_xlsform, write_xlsform_csvs
from chw_navigator.xlsform_import import import_xlsform_files
from test_support import create_test_run, reset_suite_runs


class DateHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_suite_runs("date_helpers")

    def setUp(self) -> None:
        self.test_run = create_test_run(
            suite_name="date_helpers",
            test_name=self.id().split(".")[-1],
            purpose="Verify DOB/day-serial helper execution across interpreter, XLSForm, headless, Z3, and import round-trip.",
        )
        self.document = _build_date_helper_document()
        self.cases = [
            ComparisonCase(
                name="infant_case",
                values={"v_visit_day": 120, "v_birth_day": 75},
                missing=set(),
                category="explicit",
                tags=["dob"],
            ),
            ComparisonCase(
                name="older_case",
                values={"v_visit_day": 120, "v_birth_day": 20},
                missing=set(),
                category="explicit",
                tags=["dob"],
            ),
            ComparisonCase(
                name="missing_birth_case",
                values={"v_visit_day": 120},
                missing={"v_birth_day"},
                category="explicit",
                tags=["dob", "missing"],
            ),
        ]

    def test_compare_backends_supports_day_serial_date_helpers(self) -> None:
        results = compare_backends(self.document, patient_cases=self.cases)
        self.assertTrue(results)
        self.assertTrue(all(result.ok for result in results))

        infant = next(item for item in results if item.name == "infant_case")
        self.assertEqual(45, infant.interpreter_outputs["o_age_days"])
        self.assertEqual(1, infant.interpreter_outputs["o_age_months"])
        self.assertFalse(infant.interpreter_outputs["o_birth_missing"])

        missing_birth = next(item for item in results if item.name == "missing_birth_case")
        self.assertEqual(0, missing_birth.interpreter_outputs["o_age_days"])
        self.assertEqual(0, missing_birth.interpreter_outputs["o_age_months"])
        self.assertTrue(missing_birth.interpreter_outputs["o_birth_missing"])

    def test_interpreter_handles_missingness_helper(self) -> None:
        result = evaluate_document(self.document, {"v_visit_day": 120}, {"v_birth_day"})
        self.assertFalse(result.predicates["p_has_birth_date"])
        self.assertEqual(0, result.outputs["o_age_days"])
        self.assertEqual(0, result.outputs["o_age_months"])
        self.assertTrue(result.outputs["o_birth_missing"])

    def test_generated_xlsform_round_trips_date_helpers(self) -> None:
        built = build_xlsform(self.document)
        output_dir = self.test_run.outputs_dir / "xlsform"
        survey_path, choices_path, _ = write_xlsform_csvs(built, str(output_dir))
        imported = import_xlsform_files(
            survey_path,
            choices_path,
            guideline_id="date_helper_imported",
            default_predicate_missingness=MissingnessPolicy.PROPAGATE_UNKNOWN,
        )
        results = compare_document_pair(self.document, imported, self.cases, label="date helper import")
        self.assertTrue(results)
        self.assertTrue(all(result.ok for result in results))


def _build_date_helper_document() -> ClinicalIRDocument:
    return ClinicalIRDocument.from_dict(
        json.loads(
            json.dumps(
                {
                    "metadata": {"ir_version": 1, "guideline_id": "date_helper_demo"},
                    "variables": {
                        "v_visit_day": {
                            "type": "int",
                            "domain": {"min": 0, "max": 100000},
                            "allowed_missingness": False,
                            "multivalue": False,
                            "provenance": [{"source_id": "TEST_DATE_HELPER", "kind": "unit_test"}],
                        },
                        "v_birth_day": {
                            "type": "int",
                            "domain": {"min": 0, "max": 100000},
                            "allowed_missingness": True,
                            "multivalue": False,
                            "provenance": [{"source_id": "TEST_DATE_HELPER", "kind": "unit_test"}],
                        },
                    },
                    "predicates": {
                        "p_has_birth_date": {
                            "inputs_used": ["v_birth_day"],
                            "expression": {
                                "kind": "not",
                                "arg": {
                                    "kind": "call",
                                    "fn": "is_missing",
                                    "args": [{"kind": "var", "id": "v_birth_day"}],
                                },
                            },
                            "missingness_policy": "propagate_unknown",
                            "provenance": [{"source_id": "TEST_DATE_HELPER", "kind": "unit_test"}],
                        }
                    },
                    "decisions": {
                        "d_age_logic": {
                            "hit_policy": "FIRST",
                            "rules": [
                                {
                                    "id": "r_has_birth",
                                    "when": {"kind": "pred", "id": "p_has_birth_date"},
                                    "then": {
                                        "o_age_days": {
                                            "kind": "call",
                                            "fn": "date_diff_days",
                                            "args": [
                                                {"kind": "var", "id": "v_visit_day"},
                                                {"kind": "var", "id": "v_birth_day"},
                                            ],
                                        },
                                        "o_age_months": {
                                            "kind": "call",
                                            "fn": "age_months_from_date",
                                            "args": [
                                                {"kind": "var", "id": "v_visit_day"},
                                                {"kind": "var", "id": "v_birth_day"},
                                            ],
                                        },
                                        "o_birth_missing": False,
                                    },
                                    "provenance": [{"source_id": "TEST_DATE_HELPER", "kind": "unit_test"}],
                                },
                                {
                                    "id": "r_no_birth",
                                    "when": {"kind": "else"},
                                    "then": {
                                        "o_age_days": 0,
                                        "o_age_months": 0,
                                        "o_birth_missing": True,
                                    },
                                    "provenance": [{"source_id": "TEST_DATE_HELPER", "kind": "unit_test"}],
                                },
                            ],
                            "provenance": [{"source_id": "TEST_DATE_HELPER", "kind": "unit_test"}],
                        }
                    },
                    "outputs": {
                        "o_age_days": {
                            "type": "int",
                            "provenance": [{"source_id": "TEST_DATE_HELPER", "kind": "unit_test"}],
                        },
                        "o_age_months": {
                            "type": "int",
                            "provenance": [{"source_id": "TEST_DATE_HELPER", "kind": "unit_test"}],
                        },
                        "o_birth_missing": {
                            "type": "bool",
                            "provenance": [{"source_id": "TEST_DATE_HELPER", "kind": "unit_test"}],
                        },
                    },
                }
            )
        )
    )


if __name__ == "__main__":
    unittest.main()
