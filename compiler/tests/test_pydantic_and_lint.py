from __future__ import annotations

import sys
import unittest
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
EXAMPLES = ROOT / "examples"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.clinical_ir import ClinicalIRDocument
from chw_navigator.cht_backend import build_cht_lowering_plan, write_cht_adapter_stub
from chw_navigator.lint import lint_document
from chw_navigator.validator import validate_document
from test_support import create_test_run, reset_suite_runs


class PydanticAndLintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_suite_runs("pydantic_and_lint")

    def setUp(self) -> None:
        self.test_run = create_test_run(
            suite_name="pydantic_and_lint",
            test_name=self.id().split(".")[-1],
            purpose="Schema, lint, and CHT-lowering tests for the richer Clinical IR contract.",
            input_paths=(EXAMPLES / "pneumonia.ir.json",),
        )

    def test_example_pneumonia_is_validation_clean(self) -> None:
        payload = json.loads((EXAMPLES / "pneumonia.ir.json").read_text(encoding="utf-8"))
        document = ClinicalIRDocument.from_dict(payload)
        self.assertEqual([], validate_document(document))
        self.assertEqual([], [issue for issue in lint_document(document) if issue.level == "ERROR"])

    def test_ir_schema_rejects_extra_fields_early(self) -> None:
        payload = {
            "metadata": {
                "ir_version": 1,
                "guideline_id": "demo",
                "sources": [{"source_id": "SRC"}],
            },
            "variables": {
                "v_age": {
                    "id": "v_age",
                    "type": "int",
                    "domain": {"min": 0, "max": 120},
                    "allowed_missingness": False,
                    "multivalue": False,
                    "provenance": [{"source_id": "SRC"}],
                    "surprise_field": "boom",
                }
            },
        }
        with self.assertRaises(ValueError) as exc:
            ClinicalIRDocument.from_dict(payload)
        self.assertIn("surprise_field", str(exc.exception))

    def test_ir_schema_rejects_invalid_history_prefix_contract(self) -> None:
        payload = {
            "metadata": {
                "ir_version": 1,
                "guideline_id": "demo",
                "sources": [{"source_id": "SRC"}],
            },
            "variables": {
                "v_birth_date": {
                    "type": "string",
                    "allowed_missingness": True,
                    "multivalue": False,
                    "source_kind": "history",
                    "history_binding": {
                        "record_key": "chw.date_of_birth",
                    },
                    "provenance": [{"source_id": "SRC"}],
                }
            },
        }
        with self.assertRaises(ValueError) as exc:
            ClinicalIRDocument.from_dict(payload)
        self.assertIn("history variables must use", str(exc.exception))

    def test_ir_schema_rejects_invalid_phrase_binding_key(self) -> None:
        payload = {
            "metadata": {
                "ir_version": 1,
                "guideline_id": "demo",
                "sources": [{"source_id": "SRC"}],
            },
            "outputs": {
                "o_alert": {
                    "type": "bool",
                    "provenance": [{"source_id": "SRC"}],
                }
            },
            "phrase_bindings": {
                "o_alert": {
                    "message_key": "bad_key"
                }
            },
        }
        with self.assertRaises(ValueError) as exc:
            ClinicalIRDocument.from_dict(payload)
        self.assertIn("phrase binding key must start with one of: m_", str(exc.exception))

    def test_lint_forbids_output_references_inside_predicates(self) -> None:
        payload = {
            "metadata": {
                "ir_version": 1,
                "guideline_id": "demo",
                "sources": [{"source_id": "SRC"}],
            },
            "variables": {
                "v_flag": {
                    "id": "v_flag",
                    "type": "bool",
                    "allowed_missingness": False,
                    "multivalue": False,
                    "provenance": [{"source_id": "SRC"}],
                }
            },
            "predicates": {
                "p_bad": {
                    "id": "p_bad",
                    "inputs_used": ["v_flag"],
                    "expression": {"kind": "output", "id": "o_alert"},
                    "missingness_policy": "require_inputs",
                    "provenance": [{"source_id": "SRC"}],
                }
            },
            "phrases": {},
            "decisions": {},
            "outputs": {
                "o_alert": {
                    "id": "o_alert",
                    "type": "bool",
                    "provenance": [{"source_id": "SRC"}],
                }
            },
            "invariants": {},
            "phrase_bindings": {},
        }
        document = ClinicalIRDocument.from_dict(payload)
        issues = lint_document(document)
        messages = [issue.message for issue in issues if issue.level == "ERROR"]
        self.assertTrue(any("must not reference output 'o_alert'" in message for message in messages))

    def test_history_and_staged_decision_fields_load_and_validate(self) -> None:
        payload = {
            "metadata": {
                "ir_version": 1,
                "guideline_id": "demo",
                "sources": [{"source_id": "SRC"}],
            },
            "variables": {
                "h_date_of_birth": {
                    "type": "string",
                    "allowed_missingness": True,
                    "multivalue": False,
                    "source_kind": "history",
                    "history_binding": {
                        "record_key": "chw.date_of_birth",
                        "derivation_kind": "derived",
                        "derivation_expr": {
                            "kind": "call",
                            "fn": "age_months_from_date",
                            "args": [{"kind": "var", "id": "h_date_of_birth"}],
                        },
                    },
                    "provenance": [{"source_id": "SRC"}],
                },
                "st_age_months_effective": {
                    "type": "int",
                    "domain": {"min": 0, "max": 240},
                    "allowed_missingness": True,
                    "multivalue": False,
                    "source_kind": "state",
                    "provenance": [{"source_id": "SRC"}],
                },
            },
            "predicates": {
                "p_age_under_2m": {
                    "id": "p_age_under_2m",
                    "inputs_used": ["st_age_months_effective"],
                    "expression": {
                        "kind": "<",
                        "left": {"kind": "var", "id": "st_age_months_effective"},
                        "right": {"kind": "literal", "value": 2, "type": "int"},
                    },
                    "missingness_policy": "require_inputs",
                    "provenance": [{"source_id": "SRC"}],
                }
            },
            "actions": {
                "a_read_history": {
                    "kind": "read_history",
                    "source": "cht",
                    "outputs": ["h_date_of_birth"],
                    "mappings": [
                        {
                            "record_key": "chw.date_of_birth",
                            "target_var": "h_date_of_birth",
                        }
                    ],
                    "provenance": [{"source_id": "SRC"}],
                },
                "a_task_followup": {
                    "kind": "create_task",
                    "outputs": [],
                    "when": {"kind": "output", "id": "o_tx_demo"},
                    "task_type": "followup_visit",
                    "due_in_days": 3,
                    "priority": "routine",
                    "assignee_role": "chw",
                    "message_key": "m_followup_3d",
                    "provenance": [{"source_id": "SRC"}],
                },
            },
            "phrases": {
                "m_o_tx_demo": {
                    "entity_id": "o_tx_demo",
                    "role": "message",
                    "texts": {"en": "Treat with demo therapy."},
                    "provenance": [{"source_id": "SRC"}],
                },
                "m_followup_3d": {
                    "entity_id": "a_task_followup",
                    "role": "message",
                    "texts": {"en": "Visit again in 3 days."},
                    "provenance": [{"source_id": "SRC"}],
                }
            },
            "decisions": {
                "d_dx_demo": {
                    "hit_policy": "FIRST",
                    "stage": 1,
                    "inputs_used": ["p_age_under_2m"],
                    "rules": [
                        {
                            "id": "r_dx_demo",
                            "when": {"kind": "pred", "id": "p_age_under_2m"},
                            "then": {"o_dx_demo": True},
                            "provenance": [{"source_id": "SRC"}],
                        },
                        {
                            "id": "r_dx_demo_else",
                            "when": {"kind": "else"},
                            "then": {"o_dx_demo": False},
                            "provenance": [{"source_id": "SRC"}],
                        },
                    ],
                    "provenance": [{"source_id": "SRC"}],
                },
                "d_tx_demo": {
                    "hit_policy": "FIRST",
                    "stage": 2,
                    "inputs_used": ["o_dx_demo"],
                    "depends_on": ["d_dx_demo"],
                    "rules": [
                        {
                            "id": "r_tx_demo",
                            "when": {"kind": "output", "id": "o_dx_demo"},
                            "then": {"o_tx_demo": True},
                            "provenance": [{"source_id": "SRC"}],
                        },
                        {
                            "id": "r_tx_demo_else",
                            "when": {"kind": "else"},
                            "then": {"o_tx_demo": False},
                            "provenance": [{"source_id": "SRC"}],
                        },
                    ],
                    "provenance": [{"source_id": "SRC"}],
                },
            },
            "outputs": {
                "o_dx_demo": {
                    "type": "bool",
                    "provenance": [{"source_id": "SRC"}],
                },
                "o_tx_demo": {
                    "type": "bool",
                    "provenance": [{"source_id": "SRC"}],
                },
            },
            "invariants": {},
            "phrase_bindings": {},
        }
        document = ClinicalIRDocument.from_dict(payload)
        self.assertEqual([], validate_document(document))
        lint_errors = [issue for issue in lint_document(document) if issue.level == "ERROR"]
        self.assertEqual([], lint_errors)
        plan = build_cht_lowering_plan(document)
        self.assertIsNotNone(plan.today_row)
        self.assertEqual("today()", plan.today_row.calculation)
        self.assertEqual(1, len(plan.read_history_requests))
        self.assertEqual("a_read_history", plan.read_history_requests[0].action_id)
        self.assertEqual(1, len(plan.task_specs))
        self.assertEqual("followup_visit", plan.task_specs[0].task_type)
        self.assertTrue(any(item.row_name == "note_o_tx_demo" for item in plan.appearance_overrides))

    def test_age_month_neonatal_threshold_emits_lint_warning(self) -> None:
        payload = {
            "metadata": {"ir_version": 1, "guideline_id": "demo", "sources": [{"source_id": "SRC"}]},
            "variables": {
                "st_age_months_effective": {
                    "type": "int",
                    "domain": {"min": 0, "max": 24},
                    "allowed_missingness": False,
                    "multivalue": False,
                    "source_kind": "state",
                    "provenance": [{"source_id": "SRC"}],
                }
            },
            "predicates": {
                "p_under_2m": {
                    "inputs_used": ["st_age_months_effective"],
                    "expression": {
                        "kind": "<",
                        "left": {"kind": "var", "id": "st_age_months_effective"},
                        "right": {"kind": "literal", "type": "int", "value": 2},
                    },
                    "missingness_policy": "require_inputs",
                    "provenance": [{"source_id": "SRC"}],
                }
            },
            "phrases": {
                "m_age": {
                    "entity_id": "st_age_months_effective",
                    "role": "label",
                    "texts": {"en": "Effective age in months"},
                    "provenance": [{"source_id": "SRC"}],
                }
            },
            "outputs": {},
            "decisions": {},
            "invariants": {},
            "phrase_bindings": {},
        }
        document = ClinicalIRDocument.from_dict(payload)
        warnings = [issue.message for issue in lint_document(document) if issue.level == "WARNING"]
        self.assertTrue(any("neonatal threshold" in message for message in warnings))

    def test_action_message_key_must_reference_matching_message_phrase(self) -> None:
        payload = {
            "metadata": {"ir_version": 1, "guideline_id": "demo", "sources": [{"source_id": "SRC"}]},
            "variables": {},
            "predicates": {},
            "actions": {
                "a_task_followup": {
                    "kind": "create_task",
                    "outputs": [],
                    "task_type": "followup_visit",
                    "due_in_days": 3,
                    "priority": "routine",
                    "assignee_role": "chw",
                    "message_key": "m_wrong_target",
                    "provenance": [{"source_id": "SRC"}],
                }
            },
            "phrases": {
                "m_wrong_target": {
                    "entity_id": "o_tx_demo",
                    "role": "message",
                    "texts": {"en": "Visit again in 3 days."},
                    "provenance": [{"source_id": "SRC"}],
                }
            },
            "outputs": {},
            "decisions": {},
            "invariants": {},
            "phrase_bindings": {},
        }
        document = ClinicalIRDocument.from_dict(payload)
        warnings = [issue.message for issue in lint_document(document) if issue.level == "WARNING"]
        self.assertTrue(any("points to entity 'o_tx_demo' instead of 'a_task_followup'" in message for message in warnings))

    def test_cht_adapter_stub_writer_emits_expected_files(self) -> None:
        payload = json.loads((EXAMPLES / "pneumonia.ir.json").read_text(encoding="utf-8"))
        document = ClinicalIRDocument.from_dict(payload)
        plan = build_cht_lowering_plan(document)
        target_dir = self.test_run.outputs_dir / "cht_stub"
        target_dir.mkdir(parents=True, exist_ok=True)
        artifacts = write_cht_adapter_stub(plan, target_dir)
        self.assertTrue(artifacts.plan_json_path.exists())
        self.assertTrue(artifacts.history_stub_path.exists())
        self.assertTrue(artifacts.tasks_stub_path.exists())
        self.assertTrue(artifacts.readme_path.exists())


if __name__ == "__main__":
    unittest.main()
