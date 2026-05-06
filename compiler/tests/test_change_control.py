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
from chw_navigator.change_control import create_change_review_package, load_change_memo
from chw_navigator.clinical_ir import ClinicalIRDocument
from chw_navigator.cli import main as cli_main
from chw_navigator.dmn import import_dmn_decisions
from chw_navigator.lint import lint_document, lint_errors
from chw_navigator.validator import validate_document
from test_support import create_test_run, reset_suite_runs


class ChangeControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_suite_runs("change_control")

    def test_change_review_package_builds_for_example_delta(self) -> None:
        test_run = create_test_run(
            suite_name="change_control",
            test_name=self.id().split(".")[-1],
            purpose="Change-control review package generation for a guideline delta with explicit case impacts.",
            input_paths=(
                EXAMPLES / "change_memos" / "pneumonia_covid_no_test.memo.json",
                EXAMPLES / "pneumonia.ir.json",
                EXAMPLES / "pneumonia_covid_no_test.ir.json",
                EXAMPLES / "pneumonia_covid_no_test.cases.json",
            ),
        )
        memo = load_change_memo(EXAMPLES / "change_memos" / "pneumonia_covid_no_test.memo.json")
        baseline = _load_document(EXAMPLES / "pneumonia.ir.json")
        updated = _load_document(EXAMPLES / "pneumonia_covid_no_test.ir.json")

        self.assertEqual([], validate_document(updated))
        self.assertEqual([], lint_errors(lint_document(updated)))

        built = create_change_review_package(
            memo=memo,
            baseline_document=baseline,
            updated_document=updated,
            review_root=test_run.scratch_dir,
            baseline_ir_path=EXAMPLES / "pneumonia.ir.json",
            updated_ir_path=EXAMPLES / "pneumonia_covid_no_test.ir.json",
            patient_cases_path=EXAMPLES / "pneumonia_covid_no_test.cases.json",
        )

        self.assertTrue(built.review_dir.exists())
        self.assertTrue(built.summary_path.exists())
        self.assertTrue(built.semantic_diff_path.exists())
        self.assertTrue(built.xlsform_diff_path.exists())
        self.assertTrue(built.impact_map_path.exists())
        self.assertTrue(built.workflow_burden_path.exists())
        self.assertTrue((built.review_dir / "tests" / "validation" / "safety_report.json").exists())
        self.assertTrue((built.review_dir / "tests" / "validation" / "validation_report.json").exists())
        self.assertTrue((built.review_dir / "outputs" / "baseline_cht" / "cht_lowering_plan.json").exists())
        self.assertTrue((built.review_dir / "outputs" / "updated_cht" / "cht_lowering_plan.json").exists())
        self.assertTrue(built.hash_manifest_path.exists())
        self.assertIsNotNone(built.case_delta_path)
        self.assertTrue(built.case_delta_path is not None and built.case_delta_path.exists())

        semantic_diff = json.loads(built.semantic_diff_path.read_text(encoding="utf-8"))
        self.assertEqual(1, semantic_diff["variables"]["counts"]["added"])
        self.assertEqual(1, semantic_diff["outputs"]["counts"]["added"])
        impact_map = json.loads(built.impact_map_path.read_text(encoding="utf-8"))
        self.assertTrue(impact_map["changed_predicates"])
        workflow_burden = json.loads(built.workflow_burden_path.read_text(encoding="utf-8"))
        self.assertIn("delta", workflow_burden)

        case_delta = json.loads(built.case_delta_path.read_text(encoding="utf-8"))  # type: ignore[arg-type]
        self.assertEqual(4, case_delta["counts"]["total_cases"])
        self.assertEqual(1, case_delta["counts"]["changed_cases"])

        summary_text = built.summary_path.read_text(encoding="utf-8")
        self.assertIn("pneumonia-covid-no-test-v1", summary_text)
        self.assertIn("Changed explicit patient cases: `1` of `4`", summary_text)
        self.assertIn("Workflow Burden", summary_text)
        self.assertIn("Review Provenance", summary_text)
        self.assertIn("sha256", summary_text)

        readme_text = built.readme_path.read_text(encoding="utf-8")
        self.assertIn("Compiler version:", readme_text)
        self.assertIn("Purpose of the tests", readme_text)
        self.assertIn("impact_map.md", readme_text)
        self.assertIn("Key Evidence Hashes", readme_text)
        self.assertIn("artifact_hashes.json", readme_text)

    def test_build_change_review_cli_creates_example_package(self) -> None:
        test_run = create_test_run(
            suite_name="change_control",
            test_name=self.id().split(".")[-1],
            purpose="CLI smoke test for build-change-review using the existing example delta.",
            input_paths=(
                EXAMPLES / "change_memos" / "pneumonia_covid_no_test.memo.json",
                EXAMPLES / "pneumonia.ir.json",
                EXAMPLES / "pneumonia_covid_no_test.ir.json",
                EXAMPLES / "pneumonia_covid_no_test.cases.json",
            ),
        )
        review_root = test_run.scratch_dir / "cli_reviews"
        exit_code = cli_main(
            [
                "build-change-review",
                str(EXAMPLES / "change_memos" / "pneumonia_covid_no_test.memo.json"),
                str(EXAMPLES / "pneumonia.ir.json"),
                str(EXAMPLES / "pneumonia_covid_no_test.ir.json"),
                str(review_root),
                "--patients",
                str(EXAMPLES / "pneumonia_covid_no_test.cases.json"),
            ]
        )
        self.assertEqual(0, exit_code)
        review_dirs = [path for path in review_root.iterdir() if path.is_dir()]
        self.assertEqual(1, len(review_dirs))
        self.assertTrue((review_dirs[0] / "outputs" / "review" / "change_summary.md").exists())

    def test_change_review_package_captures_pneumonia_cutoff_shift(self) -> None:
        test_run = create_test_run(
            suite_name="change_control",
            test_name=self.id().split(".")[-1],
            purpose="Regression proof that a one-unit pneumonia cutoff change propagates through change review.",
            input_paths=(
                EXAMPLES / "catalogs" / "pneumonia.metadata.json",
                EXAMPLES / "catalogs" / "pneumonia.variables.csv",
                EXAMPLES / "catalogs" / "pneumonia.predicates.json",
                EXAMPLES / "catalogs" / "pneumonia.phrases.csv",
                EXAMPLES / "pneumonia.dmn",
            ),
        )
        source_dir = test_run.scratch_dir / "source"
        source_dir.mkdir(parents=True, exist_ok=True)

        updated_predicates_path = source_dir / "pneumonia.predicates.cutoff_plus_1.json"
        memo_path = source_dir / "pneumonia.cutoff_shift.memo.json"
        cases_path = source_dir / "pneumonia.cutoff_shift.cases.json"

        baseline_predicates = json.loads((EXAMPLES / "catalogs" / "pneumonia.predicates.json").read_text(encoding="utf-8"))
        updated_predicates = json.loads(json.dumps(baseline_predicates))
        _shift_old_child_fast_breathing_cutoff(updated_predicates)
        updated_predicates_path.write_text(json.dumps(updated_predicates, indent=2) + "\n", encoding="utf-8")

        cases = {
            "cases": [
                {"name": "danger_sign_unchanged", "values": {"v_age_months": 12, "v_resp_rate": 40, "v_danger_sign": True}},
                {"name": "old_child_just_below_cutoff", "values": {"v_age_months": 12, "v_resp_rate": 39, "v_danger_sign": False}},
                {"name": "old_child_at_original_cutoff", "values": {"v_age_months": 12, "v_resp_rate": 40, "v_danger_sign": False}},
                {"name": "old_child_at_new_cutoff", "values": {"v_age_months": 12, "v_resp_rate": 41, "v_danger_sign": False}},
                {"name": "infant_cutoff_unchanged", "values": {"v_age_months": 11, "v_resp_rate": 50, "v_danger_sign": False}},
            ]
        }
        cases_path.write_text(json.dumps(cases, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        memo = {
            "metadata": {
                "memo_version": 1,
                "change_id": "pneumonia-rr-cutoff-plus-1-v1",
                "title": "Raise the old-child fast-breathing cutoff by one breath per minute",
                "change_type": "modify_module",
                "effective_date": "2026-05-06",
                "applies_to": ["pneumonia_module", "children_12_months_and_older"],
                "source_provenance": [
                    "Temporary proof memo for compiler change-review validation",
                    "Predicate table cutoff adjustment exercise",
                ],
            },
            "clinical_intent": "Demonstrate that a one-unit change in the old-child fast-breathing threshold is visible throughout the authored-source, compiled, review, and QA artifacts.",
            "new_or_changed_inputs": ["No new inputs are introduced."],
            "new_predicates_needed": ["No new predicates are introduced; the existing p_fast_breathing predicate changes threshold for children 12 months and older."],
            "changed_classifications": ["Children 12 months and older now require respiratory rate >= 41 instead of >= 40 to enter the fast-breathing branch."],
            "changed_actions": ["Home-treatment recommendation should no longer fire for an old child with respiratory rate exactly 40 unless another rule path applies."],
            "priority_rules": [
                "Danger-sign referral remains highest priority.",
                "The cutpoint change affects only the fast-breathing threshold for older children.",
            ],
            "missingness_rules": ["Respiratory rate remains required for fast-breathing determination."],
            "stockout_device_rules": ["No stockout or device rule changes are introduced."],
            "safety_invariants": [
                "Danger-sign referral must remain unchanged.",
                "Infant fast-breathing threshold must remain unchanged.",
            ],
            "counseling_messages": ["No counseling text changes are introduced."],
            "follow_up": ["Continue standard follow-up for fast-breathing pneumonia when the updated threshold is met."],
            "data_capture_reporting": ["No new reporting fields are introduced."],
            "sunset_review_condition": "Retire this proof artifact after the change-review workflow is accepted by the team.",
            "unresolved_questions": [],
        }
        memo_path.write_text(json.dumps(memo, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        baseline = _compose_pneumonia_document(EXAMPLES / "catalogs" / "pneumonia.predicates.json")
        updated = _compose_pneumonia_document(updated_predicates_path)
        built = create_change_review_package(
            memo=load_change_memo(memo_path),
            baseline_document=baseline,
            updated_document=updated,
            review_root=test_run.scratch_dir / "cutoff_reviews",
            patient_cases_path=cases_path,
            baseline_dmn_path=EXAMPLES / "pneumonia.dmn",
            updated_dmn_path=EXAMPLES / "pneumonia.dmn",
        )

        semantic_diff = json.loads(built.semantic_diff_path.read_text(encoding="utf-8"))
        self.assertEqual(1, semantic_diff["predicates"]["counts"]["changed"])

        case_delta = json.loads(built.case_delta_path.read_text(encoding="utf-8"))  # type: ignore[arg-type]
        self.assertEqual(5, case_delta["counts"]["total_cases"])
        self.assertEqual(1, case_delta["counts"]["changed_cases"])
        changed_case = next(item for item in case_delta["cases"] if item["name"] == "old_child_at_original_cutoff")
        self.assertFalse(changed_case["ok"])
        self.assertIn("o_home_treatment", {item["output_id"] for item in changed_case["output_changes"]})
        self.assertIn("o_no_action", {item["output_id"] for item in changed_case["output_changes"]})

        summary_text = built.summary_path.read_text(encoding="utf-8")
        self.assertIn("Changed explicit patient cases: `1` of `5`", summary_text)
        self.assertIn("predicates", summary_text)


def _load_document(path: Path) -> ClinicalIRDocument:
    return ClinicalIRDocument.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _compose_pneumonia_document(predicate_path: Path) -> ClinicalIRDocument:
    base = compose_document_from_catalogs(
        EXAMPLES / "catalogs" / "pneumonia.metadata.json",
        EXAMPLES / "catalogs" / "pneumonia.variables.csv",
        predicate_path,
        EXAMPLES / "catalogs" / "pneumonia.phrases.csv",
    )
    return import_dmn_decisions(base, str(EXAMPLES / "pneumonia.dmn"))


def _shift_old_child_fast_breathing_cutoff(payload: dict[str, object]) -> None:
    predicates = payload.get("predicates", [])
    if not isinstance(predicates, list):
        raise ValueError("predicates payload is malformed")
    for predicate in predicates:
        if not isinstance(predicate, dict):
            continue
        if predicate.get("id") != "p_fast_breathing":
            continue
        expression = predicate.get("expression", {})
        if not isinstance(expression, dict):
            continue
        args = expression.get("args", [])
        if not isinstance(args, list) or len(args) < 2:
            continue
        older_child_branch = args[1]
        if not isinstance(older_child_branch, dict):
            continue
        branch_args = older_child_branch.get("args", [])
        if not isinstance(branch_args, list) or len(branch_args) < 2:
            continue
        rr_cutoff_expr = branch_args[1]
        if not isinstance(rr_cutoff_expr, dict):
            continue
        right = rr_cutoff_expr.get("right", {})
        if not isinstance(right, dict):
            continue
        right["value"] = 41
        return
    raise ValueError("could not find p_fast_breathing older-child cutoff to shift")


if __name__ == "__main__":
    unittest.main()
