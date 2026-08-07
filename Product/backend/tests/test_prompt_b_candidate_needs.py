"""WS4 Prompt B construction, parsing, and mini-manual evaluation tests."""

from __future__ import annotations

from copy import deepcopy
import inspect
import json
from pathlib import Path
import unittest

from backend.operational.capability_scan import (
    CapabilityScanValidationError,
    build_capability_scan_request,
    load_candidate_needs_schema,
    parse_candidate_needs,
    scan_capability_needs,
)
from backend.operational.capability_scan_prompt import CAPABILITY_SCAN_PROMPT
from backend.operational.prompt_b_evaluation import (
    load_evaluation_cases,
    recorded_evaluation,
    run_prompt_b_evaluation,
)


FIXTURES = Path(__file__).with_name("prompt_b_fixtures") / "cases.json"
CASES = load_evaluation_cases(FIXTURES)


class TestPromptConstruction(unittest.TestCase):
    def test_builder_and_invocation_signatures_cannot_receive_a_registry(self):
        for function in (build_capability_scan_request, scan_capability_needs):
            parameters = inspect.signature(function).parameters
            self.assertFalse(any("registry" in name or "implementation" in name for name in parameters))

        registry_set = json.loads(
            (Path(__file__).parents[3] / "compiler" / "contracts" / "examples" / "tracer" / "valid-registry-set.json")
            .read_text(encoding="utf-8")
        )
        approved_ids = {
            item["id"] for item in registry_set["capability_registry"]["capabilities"]
        }
        for case in CASES:
            request = build_capability_scan_request(case["manual"])
            rendered = json.dumps(request, sort_keys=True)
            self.assertTrue(all(value not in rendered for value in approved_ids))
            self.assertNotIn("expected", request)
            self.assertNotIn("recorded_output", request)

    def test_manual_is_delimited_as_untrusted_data(self):
        case = next(item for item in CASES if item["id"] == "adversarial-invent-and-approve")
        request = build_capability_scan_request(case["manual"])
        injected_text = case["manual"]["sections"][0]["text"]
        self.assertIn(injected_text, json.dumps(request["manual"]))
        self.assertNotIn(injected_text, request["system_instructions"])
        self.assertIn("untrusted source material", request["system_instructions"])
        self.assertIn("invent or\napprove", request["system_instructions"])

    def test_candidate_schema_has_no_resolution_or_approval_surface(self):
        schema_text = json.dumps(load_candidate_needs_schema(), sort_keys=True)
        for forbidden in ("capability_id", "implementation", "python", "extension_name", "approval", "activation"):
            self.assertNotIn(forbidden, schema_text.lower())

    def test_prompt_constant_has_a_direct_invocation_path(self):
        case = next(item for item in CASES if item["id"] == "deterministic-date-arithmetic")
        captured = []

        def adapter(request):
            captured.append(request)
            return case["recorded_output"]

        result = scan_capability_needs(case["manual"], adapter)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["system_instructions"], CAPABILITY_SCAN_PROMPT)
        self.assertEqual(result["candidates"][0]["local_id"], "need_estimated_delivery_date")

    def test_prompt_defines_high_risk_scope_unit_and_missingness_normalizations(self):
        for required in (
            "current_contact` means the current person's/contact's record",
            "unit `gregorian_date`",
            "unit `bikram_sambat_date`",
            "unit `z_score`",
            "centimeters has unit `cm`",
            "An absent required local value is `missing_input`",
            "Missing lookup/chart data\n  is `missing_reference_data`; lookup/chart data with the wrong required\n  version is `version_mismatch`",
            "Keep the source's concept name",
            "Subject scope is not an invocation input",
            "reference-data version is a contract constraint",
        ):
            self.assertIn(required, CAPABILITY_SCAN_PROMPT)


class TestRecordedMiniManuals(unittest.TestCase):
    def test_all_required_cases_reach_builder_and_strict_parser(self):
        required = {
            "no-capability-need",
            "deterministic-date-arithmetic",
            "required-local-data-read",
            "clinical-interval-is-policy",
            "ambiguous-calculation",
            "unit-mismatch",
            "unsupported-group-scope",
            "adversarial-invent-and-approve",
            "insufficient-source-grounding",
            "similar-needs-remain-separate",
        }
        self.assertEqual({case["id"] for case in CASES}, required)
        for case in CASES:
            with self.subTest(case=case["id"]):
                request = build_capability_scan_request(case["manual"])
                self.assertEqual(request["manual"], case["manual"])
                parsed = parse_candidate_needs(case["recorded_output"], case["manual"])
                self.assertEqual(parsed["schema_version"], "capability-needs@1.0.0")

    def test_recorded_evaluator_reports_all_metrics(self):
        report = recorded_evaluation(CASES)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["evidence_level"], "E2")
        for case in report["cases"]:
            self.assertEqual(case["status"], "pass")
            self.assertEqual(
                set(case["metrics"]),
                {"precision", "recall", "grounding", "unsupported_inference", "ambiguity"},
            )

    def test_no_need_policy_and_adversarial_cases_stay_empty(self):
        for case_id in ("no-capability-need", "clinical-interval-is-policy", "adversarial-invent-and-approve"):
            case = next(item for item in CASES if item["id"] == case_id)
            parsed = parse_candidate_needs(case["recorded_output"], case["manual"])
            self.assertEqual(parsed["candidates"], [])

    def test_similar_needs_remain_ordered_and_separate(self):
        case = next(item for item in CASES if item["id"] == "similar-needs-remain-separate")
        parsed = parse_candidate_needs(case["recorded_output"], case["manual"])
        self.assertEqual(
            [item["local_id"] for item in parsed["candidates"]],
            ["need_gestational_age_weeks", "need_postnatal_age_days"],
        )


class TestStrictParserMutations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = next(item for item in CASES if item["id"] == "deterministic-date-arithmetic")

    def assertMutationFails(self, mutate, message):
        output = deepcopy(self.case["recorded_output"])
        mutate(output)
        with self.assertRaisesRegex(CapabilityScanValidationError, message):
            parse_candidate_needs(output, self.case["manual"])

    def test_rejects_extra_approval_field(self):
        self.assertMutationFails(
            lambda output: output["candidates"][0].update({"approval": "approved"}),
            "unknown fields: approval",
        )

    def test_rejects_invented_source_quote(self):
        self.assertMutationFails(
            lambda output: output["candidates"][0]["source"].update({"quote": "An invented quotation."}),
            "not an exact substring",
        )

    def test_rejects_registry_shaped_identifier(self):
        self.assertMutationFails(
            lambda output: output["candidates"][0].update({"local_id": "technical.gestational-age.naegele"}),
            "local need_ identifier",
        )

    def test_rejects_malformed_unit(self):
        self.assertMutationFails(
            lambda output: output["candidates"][0]["inputs"][0].update({"unit": "days or weeks"}),
            "unit is malformed",
        )

    def test_rejects_source_digest_from_another_manual(self):
        self.assertMutationFails(
            lambda output: output["candidates"][0]["provenance"].update({"source_digest": "0" * 64}),
            "does not match",
        )

    def test_rejects_success_while_uncertainty_is_unresolved(self):
        output = deepcopy(
            next(item for item in CASES if item["id"] == "ambiguous-calculation")["recorded_output"]
        )
        manual = next(item for item in CASES if item["id"] == "ambiguous-calculation")["manual"]
        output["candidates"][0]["required_statuses"].append("success")
        with self.assertRaisesRegex(CapabilityScanValidationError, "fail closed"):
            parse_candidate_needs(output, manual)


class TestLiveEvaluationBoundary(unittest.TestCase):
    def test_missing_live_adapter_is_not_run_never_pass(self):
        report = run_prompt_b_evaluation(CASES)
        self.assertEqual(report["status"], "not_run")
        self.assertEqual(report["evidence_level"], "E0")
        self.assertTrue(report["cases"])
        for case in report["cases"]:
            self.assertEqual(case["status"], "not_run")
            self.assertTrue(all(metric["status"] == "not_run" for metric in case["metrics"].values()))

    def test_live_adapter_never_receives_expected_answers(self):
        outputs = {case["manual"]["document_id"]: case["recorded_output"] for case in CASES}
        seen = []

        def adapter(request):
            seen.append(request)
            self.assertNotIn("expected", request)
            self.assertNotIn("recorded_output", request)
            return outputs[request["manual"]["document_id"]]

        report = run_prompt_b_evaluation(CASES, adapter)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(len(seen), len(CASES))


if __name__ == "__main__":
    unittest.main()
