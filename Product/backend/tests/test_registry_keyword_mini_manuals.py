"""Recorded mini-manual evidence for the registry-keyword architecture boundary."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from backend.operational.capability_scan import parse_candidate_needs


FIXTURE = Path(__file__).with_name("prompt_b_fixtures") / "registry_match_trials.json"
TRIAL = json.loads(FIXTURE.read_text(encoding="utf-8"))


class TestRegistryBlindNeedExtraction(unittest.TestCase):
    def test_isolated_model_detected_all_three_needs_in_valid_prompt_b_format(self):
        for case in TRIAL["cases"]:
            with self.subTest(case=case["id"]):
                parsed = parse_candidate_needs(case["registry_blind_output"], case["manual"])
                self.assertEqual(len(parsed["candidates"]), 1)
                self.assertEqual(parsed["candidates"][0]["need_kind"], case["expected_need_kind"])

    def test_registry_blind_output_contains_no_registry_selection(self):
        forbidden = {"capability_id", "registry_id", "implementation_binding", "python_symbol"}
        for case in TRIAL["cases"]:
            candidate = case["registry_blind_output"]["candidates"][0]
            self.assertTrue(forbidden.isdisjoint(candidate))
            self.assertTrue(candidate["local_id"].startswith("need_"))


class TestExactKeywordGuessing(unittest.TestCase):
    def test_hidden_registry_exact_id_guessing_was_zero_of_three(self):
        exact = [
            case["hidden_registry_guess"]["guessed_registry_id"]
            == case["expected_registry_entry_id"]
            for case in TRIAL["cases"]
        ]
        self.assertEqual(exact, [False, False, False])

    def test_visible_catalogue_can_copy_exact_ids_after_assumptions_are_clarified(self):
        selections = TRIAL["catalogue_visible_trials"]["clarified_matching_assumptions"][:3]
        expected = {case["id"]: case["expected_registry_entry_id"] for case in TRIAL["cases"]}
        catalogue_ids = {entry["entry_id"] for entry in TRIAL["synthetic_catalogue"]}
        self.assertEqual(len(selections), 3)
        for selection in selections:
            with self.subTest(case=selection["case_id"]):
                self.assertEqual(selection["status"], "matched")
                self.assertEqual(selection["entry_id"], expected[selection["case_id"]])
                self.assertIn(selection["entry_id"], catalogue_ids)

    def test_structured_catalogue_fields_are_copied_without_model_renaming(self):
        catalogue = {entry["entry_id"]: entry for entry in TRIAL["synthetic_catalogue"]}
        for selection in TRIAL["catalogue_visible_trials"]["structured_copy_fidelity"]:
            with self.subTest(case=selection["case_id"]):
                self.assertEqual(selection["status"], "matched")
                self.assertEqual(selection["copied_signature"], catalogue[selection["entry_id"]])

    def test_visible_catalogue_abstains_when_entry_is_absent_or_ambiguous(self):
        selections = {
            item["case_id"]: item
            for item in TRIAL["catalogue_visible_trials"]["clarified_matching_assumptions"]
        }
        self.assertEqual(selections["dob_entry_absent"], {
            "case_id": "dob_entry_absent", "status": "no_match", "entry_id": None,
        })
        self.assertEqual(selections["dob_entry_ambiguous"], {
            "case_id": "dob_entry_ambiguous", "status": "ambiguous", "entry_id": None,
        })

    def test_unclarified_source_or_matching_rules_do_not_silently_select(self):
        selections = TRIAL["catalogue_visible_trials"]["unclarified"]
        self.assertEqual([item["status"] for item in selections], ["matched", "no_match", "no_match"])


if __name__ == "__main__":
    unittest.main()
