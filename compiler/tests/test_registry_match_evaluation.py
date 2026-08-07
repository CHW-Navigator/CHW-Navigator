from __future__ import annotations

from copy import deepcopy
import json
import unittest

from chw_navigator.registry_match_evaluation import (
    AdapterObservation,
    RegistryMatchEvaluationError,
    build_synthetic_evaluation_plan,
    parse_evaluation_plan,
    parse_evaluation_report,
    recorded_perfect_adapter,
    run_predeclared_evaluation,
    seal_evaluation_plan,
)


class RegistryMatchEvaluationTests(unittest.TestCase):
    def test_frozen_matrix_is_large_balanced_and_has_no_patient_use(self) -> None:
        plan = build_synthetic_evaluation_plan()
        self.assertEqual(len(plan.cases), 36)
        self.assertTrue(plan.pilot_only)
        self.assertFalse(plan.clinical_use_permitted)
        self.assertFalse(plan.deployment_permitted)
        self.assertEqual({case.group for case in plan.cases}, {
            "positive", "clarification", "no_match", "ambiguous", "adversarial", "schema_gap"
        })
        for case in plan.cases:
            adapter_input = case.adapter_input().model_dump(mode="json")
            self.assertNotIn("expected_", json.dumps(adapter_input))
            self.assertNotIn("group", adapter_input)

    def test_replay_scores_each_stage_and_surfaces_schema_gaps(self) -> None:
        report = run_predeclared_evaluation(
            build_synthetic_evaluation_plan(), recorded_perfect_adapter, run_kind="recorded_synthetic_replay"
        )
        self.assertEqual(report["overall_status"], "evaluation_passed_with_registry_schema_gaps")
        self.assertEqual(report["evidence_ceiling"], "E2")
        self.assertEqual(report["metrics"]["case_count"], 36)
        self.assertEqual(report["metrics"]["false_unique_count"], 0)
        self.assertEqual(set(report["registry_schema_gaps"]), {
            "parameter_value_sets", "parameter_requiredness", "parameter_ownership", "reference_data_identity"
        })
        self.assertTrue(all(not row["false_unique"] for row in report["cases"]))

    def test_wrong_unique_match_fails_even_when_adapter_claims_confidence_nowhere(self) -> None:
        def unsafe_adapter(case):
            return AdapterObservation(blind_outcome="extracted", match_outcome="unique_match")

        report = run_predeclared_evaluation(
            build_synthetic_evaluation_plan(), unsafe_adapter, run_kind="fresh_adapter_run"
        )
        self.assertEqual(report["overall_status"], "evaluation_failed")
        self.assertGreater(report["metrics"]["false_unique_count"], 0)
        self.assertEqual(report["evidence_ceiling"], "E1")

    def test_missing_group_or_tampered_plan_digest_fails_closed(self) -> None:
        payload = build_synthetic_evaluation_plan().model_dump(mode="json")
        payload["cases"] = [case for case in payload["cases"] if case["group"] != "ambiguous"]
        payload["content_digest"] = "sha256:" + "0" * 64
        with self.assertRaises(RegistryMatchEvaluationError):
            parse_evaluation_plan(seal_evaluation_plan(payload))

        payload = build_synthetic_evaluation_plan().model_dump(mode="json")
        payload["cases"][0]["expected_match_outcome"] = "no_match"
        with self.assertRaises(RegistryMatchEvaluationError):
            parse_evaluation_plan(payload)

    def test_report_digest_detects_tampering(self) -> None:
        report = run_predeclared_evaluation(
            build_synthetic_evaluation_plan(), recorded_perfect_adapter, run_kind="recorded_synthetic_replay"
        )
        changed = deepcopy(report)
        changed["metrics"]["false_unique_count"] = 99
        with self.assertRaises(RegistryMatchEvaluationError):
            parse_evaluation_report(changed)
