from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

EXAMPLES = ROOT / "examples" / "ws5"
TRACER = ROOT / "examples" / "tracer"
GOVERNED = ROOT / "contracts" / "examples" / "governance" / "valid-registry-set-v2.json"
REGISTRY_TRIALS = ROOT.parent / "Product" / "backend" / "tests" / "prompt_b_fixtures" / "registry_match_trials.json"

from chw_navigator.cht_local_data import load_cht_local_data_registry
from chw_navigator.cli import main
from chw_navigator.registry_governance import parse_registry_set_v2
from chw_navigator.registry_match import (
    RegistryMatchError,
    build_registry_match_catalogue,
    build_registry_match_request,
    evaluate_registry_match_proposal,
    parse_registry_match_catalogue,
    parse_registry_match_proposal,
    parse_registry_match_review,
    propose_registry_match,
    seal_registry_match_review,
    write_registry_match_review,
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def inputs():
    source = load(EXAMPLES / "candidate-capability-needs.json")
    product = load(EXAMPLES / "product-clinical-logic.json")
    registry = parse_registry_set_v2(load(GOVERNED))
    local = load_cht_local_data_registry(TRACER / "local-data-bindings.json")
    catalogue = build_registry_match_catalogue(registry, local)
    return source, product, registry, local, catalogue


def proposal_payload(source: dict, product: dict, catalogue, **changes) -> dict:
    request = build_registry_match_request(
        source, catalogue, product, "need_gestational_age_naegele"
    )
    payload = {
        "schema_version": "registry-match-proposal@1.0.0",
        "source_candidate_digest": request["source_candidate_digest"],
        "catalogue_digest": request["catalogue_digest"],
        "need_id": "need_gestational_age_naegele",
        "outcome": "unique_match",
        "selected_entry_ref": "technical.gestational-age.naegele@1.0.0",
        "confidence_percent": 96,
        "alternatives": [],
        "parameter_mappings": [
            {
                "direction": "input",
                "candidate_name": "last_menstrual_period_date",
                "registry_name": "lmp_date",
                "variable_id": "st_lmp_date_h",
            },
            {
                "direction": "input",
                "candidate_name": "reference_date",
                "registry_name": "reference_date",
                "variable_id": "st_reference_date",
            },
            {
                "direction": "output",
                "candidate_name": "gestational_age_weeks",
                "registry_name": "ga_weeks",
                "variable_id": "st_ga_weeks",
            },
            {
                "direction": "output",
                "candidate_name": "gestational_age_days_remainder",
                "registry_name": "ga_days_remainder",
                "variable_id": "st_ga_days_remainder",
            },
            {
                "direction": "output",
                "candidate_name": "estimated_delivery_date",
                "registry_name": "edd",
                "variable_id": "st_edd",
            },
        ],
        "status_target_var": "st_ga_status",
        "local_action_id": None,
        "local_fail_mode": None,
        "unresolved_questions": [],
        "rationale": "The operation, ordered data contract, target, and scope correspond.",
    }
    payload.update(changes)
    return payload


def reseal_catalogue(payload: dict) -> dict:
    sealed = deepcopy(payload)
    sealed.pop("content_digest", None)
    encoded = json.dumps(sealed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sealed["content_digest"] = "sha256:" + hashlib.sha256(encoded).hexdigest()
    return sealed


def local_candidate(unit: str | None = "calendar_date") -> dict:
    return {
        "schema_version": "capability-needs@1.0.0",
        "candidates": [{
            "local_id": "need_recent_lmp_read",
            "need_kind": "local_data_read",
            "problem": "Read the most recent LMP date for the current contact.",
            "inputs": [],
            "outputs": [{"name": "last_menstrual_period_date", "data_type": "date", "unit": unit}],
            "required_statuses": ["success", "missing_input"],
            "failure_behavior": "block",
            "subject_scope": "current_contact",
            "uncertainty": {"status": "none", "details": None},
            "source": {
                "document_id": "mini-local-read",
                "page": "1",
                "section": "Prior information",
                "quote": "Read the most recent LMP date for the current contact.",
            },
            "provenance": {"origin": "manual", "source_digest": "0" * 64},
        }],
    }


def recorded_trial_catalogue() -> tuple[dict, object]:
    trial = load(REGISTRY_TRIALS)
    entries = []
    for raw in trial["synthetic_catalogue"]:
        kind = raw["kind"]
        statuses = raw["statuses"]
        if kind == "local_data_read":
            statuses = ["available", "missing", "stale"]
        normalized_inputs = deepcopy(raw.get("inputs", []))
        normalized_outputs = deepcopy(raw["outputs"])
        for parameter in [*normalized_inputs, *normalized_outputs]:
            if parameter["type"] == "code":
                parameter["type"] = "choice"
        entry = {
            "entry_ref": raw["entry_id"],
            "entry_digest": "sha256:" + hashlib.sha256(
                json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "kind": kind,
            "family": raw.get("family"),
            "operation": raw.get("operation"),
            "semantic_name": raw.get("semantic_name"),
            "description": None,
            "inputs": normalized_inputs,
            "outputs": normalized_outputs,
            "statuses": statuses,
            "target_profile": raw["target_profile"],
            "subject_scope": "current_contact" if raw["subject_scope"] == "none" else raw["subject_scope"],
        }
        entries.append(entry)
    payload = {
        "schema_version": "registry-match-catalogue@1.0.0",
        "content_digest": "sha256:" + "0" * 64,
        "registry_set_digest": "sha256:" + "1" * 64,
        "local_data_registry_digest": "sha256:" + "2" * 64,
        "entries": entries,
    }
    return trial, parse_registry_match_catalogue(reseal_catalogue(payload))


def trial_proposal_inputs(case: dict, catalogue, *, clarify: bool) -> tuple[dict, dict, object]:
    source = deepcopy(case["registry_blind_output"])
    candidate = source["candidates"][0]
    entry = next(item for item in catalogue.entries if item.entry_ref == case["expected_registry_entry_id"])
    mappings: list[dict[str, str]] = []
    mapping_names = {
        "dob_local_read": {
            "output": {"date_of_birth": "birth_event_date"},
        },
        "who_height_for_age": {
            "input": {
                "sex": "sex",
                "date_of_birth": "birth_date",
                "measurement_date": "measurement_date",
                "standing_height": "height_cm",
            },
            "output": {"height_for_age_z_score": "z_score"},
        },
        "nepali_elapsed_days": {
            "input": {"start_date": "start_date", "end_date": "end_date"},
            "output": {"elapsed_days": "elapsed_days"},
        },
    }[case["id"]]
    variables = []
    parameters = {
        "input": {item.name: item for item in entry.inputs},
        "output": {item.name: item for item in entry.outputs},
    }
    for direction in ("input", "output"):
        for candidate_name, registry_name in mapping_names.get(direction, {}).items():
            variable_id = f"st_{direction}_{registry_name}"
            parameter = parameters[direction][registry_name]
            mappings.append({
                "direction": direction,
                "candidate_name": candidate_name,
                "registry_name": registry_name,
                "variable_id": variable_id,
            })
            variables.append({
                "id": variable_id,
                "data_type": parameter.type,
                "unit": parameter.unit,
                "domain": None,
            })
            if clarify:
                raw_parameter = next(item for item in candidate[direction + "s"] if item["name"] == candidate_name)
                raw_parameter["unit"] = parameter.unit
    if clarify:
        candidate["subject_scope"] = entry.subject_scope
    status_target = None
    local_action = None
    local_mode = None
    if entry.kind == "technical_calculation":
        status_target = "st_match_status"
        variables.append({
            "id": status_target,
            "data_type": "choice",
            "unit": "none",
            "domain": list(entry.statuses),
        })
    else:
        local_action = "a_read_birth_date"
        local_mode = "hard_error"
    product = {"variables": variables}
    request = build_registry_match_request(source, catalogue, product, candidate["local_id"])
    proposal = parse_registry_match_proposal({
        "schema_version": "registry-match-proposal@1.0.0",
        "source_candidate_digest": request["source_candidate_digest"],
        "catalogue_digest": request["catalogue_digest"],
        "need_id": candidate["local_id"],
        "outcome": "unique_match",
        "selected_entry_ref": entry.entry_ref,
        "confidence_percent": 99,
        "alternatives": [],
        "parameter_mappings": mappings,
        "status_target_var": status_target,
        "local_action_id": local_action,
        "local_fail_mode": local_mode,
        "unresolved_questions": [],
        "rationale": "Recorded catalogue-visible proposal for the focused mini-manual trial.",
    })
    return source, product, proposal


class RegistryVisibleRequestTests(unittest.TestCase):
    def test_request_sees_catalogue_but_not_expected_answers_or_implementation_bindings(self):
        source, product, _, _, catalogue = inputs()
        request = build_registry_match_request(
            source, catalogue, product, "need_gestational_age_naegele"
        )
        rendered = json.dumps(request, sort_keys=True)
        self.assertIn("technical.gestational-age.naegele@1.0.0", rendered)
        self.assertNotIn("expected", request)
        self.assertNotIn("implementation_binding", rendered)
        self.assertNotIn("python_symbol", rendered)
        self.assertIn("advisory", request["system_instructions"])

    def test_proposal_schema_carries_only_entry_refs_not_registry_rewrites(self):
        schema = build_registry_match_request(
            inputs()[0], inputs()[4], inputs()[1], "need_gestational_age_naegele"
        )["output_schema"]
        rendered = json.dumps(schema, sort_keys=True)
        self.assertIn("selected_entry_ref", rendered)
        for forbidden in ("family", "operation", "statuses", "implementation_binding"):
            self.assertNotIn(f'"{forbidden}"', rendered)

    def test_explicit_model_adapter_receives_no_expected_answer_and_is_strictly_parsed(self):
        source, product, _, _, catalogue = inputs()
        expected = proposal_payload(source, product, catalogue)
        seen = []

        def adapter(request):
            seen.append(request)
            self.assertNotIn("expected", request)
            return json.dumps(expected)

        proposal = propose_registry_match(
            source,
            catalogue,
            product,
            "need_gestational_age_naegele",
            adapter,
        )
        self.assertEqual(len(seen), 1)
        self.assertEqual(proposal.selected_entry_ref, "technical.gestational-age.naegele@1.0.0")

        with self.assertRaisesRegex(RegistryMatchError, "must be JSON"):
            propose_registry_match(
                source,
                catalogue,
                product,
                "need_gestational_age_naegele",
                lambda request: "not json",
            )

    def test_committed_tracer_proposal_is_bound_to_current_candidate_and_catalogue(self):
        source, product, _, _, catalogue = inputs()
        self.assertEqual(
            load(EXAMPLES / "registry-match-proposal.json"),
            proposal_payload(source, product, catalogue),
        )


class FocusedMiniManualMatchTests(unittest.TestCase):
    def test_original_three_blind_outputs_do_not_auto_match_despite_99_percent_confidence(self):
        trial, catalogue = recorded_trial_catalogue()
        for case in trial["cases"]:
            with self.subTest(case=case["id"]):
                source, product, proposal = trial_proposal_inputs(
                    case, catalogue, clarify=False
                )
                package = evaluate_registry_match_proposal(
                    source, proposal, catalogue, product
                )
                self.assertIn(package["outcome"], {"no_match", "needs_clarification"})
                self.assertIsNone(package["proposed_binding"])
                self.assertFalse(package["executable_eligible"])

    def test_clarified_units_and_scope_allow_all_three_to_reach_human_review(self):
        trial, catalogue = recorded_trial_catalogue()
        for case in trial["cases"]:
            with self.subTest(case=case["id"]):
                source, product, proposal = trial_proposal_inputs(
                    case, catalogue, clarify=True
                )
                package = evaluate_registry_match_proposal(
                    source, proposal, catalogue, product
                )
                self.assertEqual(package["outcome"], "unique_match")
                self.assertIsNotNone(package["proposed_binding"])
                self.assertEqual(
                    package["selected_entry"]["entry_ref"],
                    case["expected_registry_entry_id"],
                )
                self.assertFalse(package["executable_eligible"])
                self.assertEqual(package["human_review"]["decision"], "not_supplied")


class DeterministicMatchReviewTests(unittest.TestCase):
    def test_unique_capability_match_copies_entry_and_proposes_exact_ws5_binding(self):
        source, product, _, _, catalogue = inputs()
        proposal = parse_registry_match_proposal(proposal_payload(source, product, catalogue))
        package = evaluate_registry_match_proposal(source, proposal, catalogue, product)
        selected = next(
            item for item in catalogue.entries
            if item.entry_ref == "technical.gestational-age.naegele@1.0.0"
        )
        self.assertEqual(package["outcome"], "unique_match")
        self.assertEqual(package["selected_entry"], selected.model_dump(mode="json"))
        self.assertEqual(package["proposed_binding"], load(EXAMPLES / "reviewed-capability-needs.json")["needs"][0])
        self.assertFalse(package["executable_eligible"])
        self.assertEqual(package["human_review"]["decision"], "not_supplied")
        self.assertTrue(all(
            item["status"] == "pass" for item in package["checks"]
            if item["status"] != "warning"
        ))

        reordered = proposal_payload(source, product, catalogue)
        reordered["parameter_mappings"].reverse()
        reordered_package = evaluate_registry_match_proposal(
            source, parse_registry_match_proposal(reordered), catalogue, product
        )
        self.assertEqual(reordered_package["proposed_binding"], package["proposed_binding"])

    def test_confidence_is_advisory_and_cannot_override_a_hard_unit_conflict(self):
        source, product, _, _, catalogue = inputs()
        changed = deepcopy(source)
        changed["candidates"][0]["outputs"][0]["unit"] = "days"
        proposal = parse_registry_match_proposal(
            proposal_payload(changed, product, catalogue, confidence_percent=99.9)
        )
        package = evaluate_registry_match_proposal(changed, proposal, catalogue, product)
        self.assertEqual(package["outcome"], "no_match")
        self.assertIsNone(package["proposed_binding"])
        self.assertIn("fail", {item["status"] for item in package["checks"]})
        self.assertFalse(package["model_assessment"]["authoritative"])

    def test_review_digest_is_sealed_after_numeric_normalization(self):
        source, product, _, _, catalogue = inputs()
        proposal = parse_registry_match_proposal(proposal_payload(source, product, catalogue))
        package = evaluate_registry_match_proposal(source, proposal, catalogue, product)
        integer_spelling = deepcopy(package)
        integer_spelling["model_assessment"]["example_display_thresholds"] = {
            "top_at_least": 90,
            "second_at_most": 5,
        }
        float_spelling = deepcopy(package)
        float_spelling["model_assessment"]["example_display_thresholds"] = {
            "top_at_least": 90.0,
            "second_at_most": 5.0,
        }
        self.assertEqual(
            seal_registry_match_review(integer_spelling),
            seal_registry_match_review(float_spelling),
        )

    def test_low_confidence_flags_review_but_does_not_change_hard_match_result(self):
        source, product, _, _, catalogue = inputs()
        proposal = parse_registry_match_proposal(
            proposal_payload(source, product, catalogue, confidence_percent=62)
        )
        package = evaluate_registry_match_proposal(source, proposal, catalogue, product)
        self.assertEqual(package["outcome"], "unique_match")
        self.assertEqual(
            package["model_assessment"]["example_threshold_result"],
            "flag_for_human_attention",
        )
        confidence_check = next(item for item in package["checks"] if item["check_id"] == "model_confidence")
        self.assertEqual(confidence_check["status"], "warning")
        self.assertFalse(package["executable_eligible"])

    def test_second_candidate_above_five_percent_is_visible_but_not_a_probability_gate(self):
        source, product, _, _, catalogue = inputs()
        proposal = parse_registry_match_proposal(proposal_payload(
            source,
            product,
            catalogue,
            confidence_percent=92,
            alternatives=[{
                "entry_ref": "local.person.lmp_date@1.0.0",
                "confidence_percent": 8,
                "reason": "It also mentions an LMP date but is a read, not the calculation.",
            }],
        ))
        package = evaluate_registry_match_proposal(source, proposal, catalogue, product)
        self.assertEqual(package["outcome"], "unique_match")
        self.assertEqual(package["model_assessment"]["second_confidence_percent"], 8)
        self.assertEqual(
            package["model_assessment"]["example_threshold_result"],
            "flag_for_human_attention",
        )

    def test_duplicate_complete_registry_signature_forces_ambiguous(self):
        source, product, _, _, catalogue = inputs()
        payload = catalogue.model_dump(mode="json")
        original = next(
            item for item in payload["entries"]
            if item["entry_ref"] == "technical.gestational-age.naegele@1.0.0"
        )
        duplicate = deepcopy(original)
        duplicate["entry_ref"] = "technical.gestational-age.alternative@1.0.0"
        duplicate["entry_digest"] = "sha256:" + "f" * 64
        payload["entries"].append(duplicate)
        ambiguous_catalogue = parse_registry_match_catalogue(reseal_catalogue(payload))
        proposal = parse_registry_match_proposal(
            proposal_payload(source, product, ambiguous_catalogue)
        )
        package = evaluate_registry_match_proposal(source, proposal, ambiguous_catalogue, product)
        self.assertEqual(package["outcome"], "ambiguous")
        self.assertIsNone(package["proposed_binding"])

    def test_explicit_no_match_ambiguous_and_clarification_are_preserved(self):
        source, product, _, _, catalogue = inputs()
        cases = (
            ("no_match", None, [], [], "no_match"),
            (
                "ambiguous",
                None,
                [
                    {"entry_ref": "technical.gestational-age.naegele@1.0.0", "confidence_percent": 50, "reason": "candidate one"},
                    {"entry_ref": "local.person.lmp_date@1.0.0", "confidence_percent": 50, "reason": "candidate two"},
                ],
                [],
                "ambiguous",
            ),
            (
                "needs_clarification",
                "technical.gestational-age.naegele@1.0.0",
                [],
                ["The manual does not establish the reference date."],
                "needs_clarification",
            ),
        )
        for outcome, selected, alternatives, questions, expected in cases:
            with self.subTest(outcome=outcome):
                changes = {
                    "outcome": outcome,
                    "selected_entry_ref": selected,
                    "alternatives": alternatives,
                    "unresolved_questions": questions,
                    "confidence_percent": None if outcome != "needs_clarification" else 60,
                }
                if outcome in {"no_match", "ambiguous"}:
                    changes.update({
                        "parameter_mappings": [],
                        "status_target_var": None,
                    })
                proposal = parse_registry_match_proposal(
                    proposal_payload(source, product, catalogue, **changes)
                )
                package = evaluate_registry_match_proposal(source, proposal, catalogue, product)
                self.assertEqual(package["outcome"], expected)
                self.assertFalse(package["executable_eligible"])

    def test_local_data_match_uses_exact_binding_and_stays_non_executable(self):
        _, product, _, _, catalogue = inputs()
        source = local_candidate()
        request = build_registry_match_request(source, catalogue, product, "need_recent_lmp_read")
        proposal = parse_registry_match_proposal({
            "schema_version": "registry-match-proposal@1.0.0",
            "source_candidate_digest": request["source_candidate_digest"],
            "catalogue_digest": request["catalogue_digest"],
            "need_id": "need_recent_lmp_read",
            "outcome": "unique_match",
            "selected_entry_ref": "local.person.lmp_date@1.0.0",
            "confidence_percent": 97,
            "alternatives": [],
            "parameter_mappings": [{
                "direction": "output",
                "candidate_name": "last_menstrual_period_date",
                "registry_name": "most_recent_lmp_date",
                "variable_id": "st_lmp_date_h",
            }],
            "status_target_var": None,
            "local_action_id": "a_read_recent_lmp",
            "local_fail_mode": "hard_error",
            "unresolved_questions": [],
            "rationale": "The current-contact local date and missing behavior agree.",
        })
        package = evaluate_registry_match_proposal(source, proposal, catalogue, product)
        self.assertEqual(package["outcome"], "unique_match")
        self.assertEqual(package["selected_entry"]["entry_ref"], "local.person.lmp_date@1.0.0")
        self.assertEqual(package["proposed_binding"], {
            "action_id": "a_read_recent_lmp",
            "binding_id": "local.person.lmp_date@1.0.0",
            "target_var": "st_lmp_date_h",
            "recorded_at_target_var": None,
            "fail_mode": "hard_error",
        })
        self.assertFalse(package["executable_eligible"])

    def test_missing_manual_unit_or_scope_mismatch_needs_clarification(self):
        _, product, _, _, catalogue = inputs()
        for source in (local_candidate(None), local_candidate()):
            if source["candidates"][0]["outputs"][0]["unit"] is not None:
                source["candidates"][0]["subject_scope"] = "individual"
            request = build_registry_match_request(source, catalogue, product, "need_recent_lmp_read")
            proposal = parse_registry_match_proposal({
                "schema_version": "registry-match-proposal@1.0.0",
                "source_candidate_digest": request["source_candidate_digest"],
                "catalogue_digest": request["catalogue_digest"],
                "need_id": "need_recent_lmp_read",
                "outcome": "unique_match",
                "selected_entry_ref": "local.person.lmp_date@1.0.0",
                "confidence_percent": 99,
                "alternatives": [],
                "parameter_mappings": [{
                    "direction": "output",
                    "candidate_name": "last_menstrual_period_date",
                    "registry_name": "most_recent_lmp_date",
                    "variable_id": "st_lmp_date_h",
                }],
                "status_target_var": None,
                "local_action_id": "a_read_recent_lmp",
                "local_fail_mode": "hard_error",
                "unresolved_questions": [],
                "rationale": "A high confidence assertion must still pass hard checks.",
            })
            package = evaluate_registry_match_proposal(source, proposal, catalogue, product)
            self.assertEqual(package["outcome"], "needs_clarification")
            self.assertIsNone(package["proposed_binding"])

    def test_stale_digests_unknown_alternatives_and_unknown_fields_fail_closed(self):
        source, product, _, _, catalogue = inputs()
        stale = proposal_payload(source, product, catalogue)
        stale["source_candidate_digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(RegistryMatchError, "exact source candidate"):
            evaluate_registry_match_proposal(
                source, parse_registry_match_proposal(stale), catalogue, product
            )

        stale_catalogue = proposal_payload(source, product, catalogue)
        stale_catalogue["catalogue_digest"] = "sha256:" + "9" * 64
        with self.assertRaisesRegex(RegistryMatchError, "exact registry-match catalogue"):
            evaluate_registry_match_proposal(
                source, parse_registry_match_proposal(stale_catalogue), catalogue, product
            )

        unknown = proposal_payload(source, product, catalogue)
        unknown["alternatives"] = [{
            "entry_ref": "technical.not-present@1.0.0",
            "confidence_percent": 1,
            "reason": "deliberate negative case",
        }]
        with self.assertRaisesRegex(RegistryMatchError, "alternative is not in the catalogue"):
            evaluate_registry_match_proposal(
                source, parse_registry_match_proposal(unknown), catalogue, product
            )

        extra = proposal_payload(source, product, catalogue)
        extra["approval"] = "approved"
        with self.assertRaisesRegex(RegistryMatchError, "Extra inputs"):
            parse_registry_match_proposal(extra)

        contradictory = proposal_payload(source, product, catalogue)
        contradictory["unresolved_questions"] = ["Still unknown"]
        with self.assertRaisesRegex(RegistryMatchError, "unique_match cannot carry"):
            parse_registry_match_proposal(contradictory)

        selected_again = proposal_payload(source, product, catalogue)
        selected_again["alternatives"] = [{
            "entry_ref": selected_again["selected_entry_ref"],
            "confidence_percent": 1,
            "reason": "A selected entry cannot also be presented as its own alternative.",
        }]
        with self.assertRaisesRegex(RegistryMatchError, "cannot also be a proposal alternative"):
            parse_registry_match_proposal(selected_again)

    def test_blinded_candidate_is_strictly_revalidated_at_the_match_boundary(self):
        source, product, _, _, catalogue = inputs()
        malformed = deepcopy(source)
        malformed["candidates"][0]["approval"] = "approved"
        with self.assertRaisesRegex(RegistryMatchError, "invalid source candidate artifact"):
            build_registry_match_request(
                malformed, catalogue, product, "need_gestational_age_naegele"
            )

        unresolved = deepcopy(source)
        unresolved["candidates"][0]["uncertainty"] = {
            "status": "insufficient_grounding",
            "details": None,
        }
        with self.assertRaisesRegex(RegistryMatchError, "invalid source candidate artifact"):
            build_registry_match_request(
                unresolved, catalogue, product, "need_gestational_age_naegele"
            )

    def test_unresolved_source_can_never_leave_a_proposed_binding(self):
        source, product, _, _, catalogue = inputs()
        unresolved = deepcopy(source)
        candidate = unresolved["candidates"][0]
        candidate["required_statuses"] = ["missing_input"]
        candidate["failure_behavior"] = "block"
        candidate["uncertainty"] = {
            "status": "insufficient_grounding",
            "details": "The manual does not establish whether this calculation is required.",
        }
        proposal = parse_registry_match_proposal(
            proposal_payload(unresolved, product, catalogue, confidence_percent=99)
        )
        package = evaluate_registry_match_proposal(
            unresolved, proposal, catalogue, product
        )
        self.assertEqual(package["outcome"], "needs_clarification")
        self.assertIsNone(package["proposed_binding"])
        self.assertFalse(package["executable_eligible"])

    def test_missing_mapping_unknown_selection_and_review_tampering_fail_closed(self):
        source, product, _, _, catalogue = inputs()
        missing = proposal_payload(source, product, catalogue)
        missing["parameter_mappings"].pop()
        package = evaluate_registry_match_proposal(
            source, parse_registry_match_proposal(missing), catalogue, product
        )
        self.assertEqual(package["outcome"], "no_match")
        self.assertIsNone(package["proposed_binding"])

        unknown = proposal_payload(
            source,
            product,
            catalogue,
            selected_entry_ref="technical.unknown@1.0.0",
            confidence_percent=100,
        )
        package = evaluate_registry_match_proposal(
            source, parse_registry_match_proposal(unknown), catalogue, product
        )
        self.assertEqual(package["outcome"], "no_match")
        self.assertIsNone(package["selected_entry"])

        valid = evaluate_registry_match_proposal(
            source,
            parse_registry_match_proposal(proposal_payload(source, product, catalogue)),
            catalogue,
            product,
        )
        valid["human_review"]["decision"] = "approved"
        with self.assertRaisesRegex(RegistryMatchError, "invalid registry-match review"):
            parse_registry_match_review(valid)

    def test_root_writer_is_deterministic(self):
        source, product, _, _, catalogue = inputs()
        proposal = proposal_payload(source, product, catalogue)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "source.json"
            product_path = root / "product.json"
            proposal_path = root / "proposal.json"
            source_path.write_text(json.dumps(source), encoding="utf-8")
            product_path.write_text(json.dumps(product), encoding="utf-8")
            proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
            one = root / "one.json"
            two = root / "two.json"
            common = {
                "source_candidate_path": source_path,
                "proposal_path": proposal_path,
                "product_logic_path": product_path,
                "registry_set_path": GOVERNED,
                "local_data_registry_path": TRACER / "local-data-bindings.json",
            }
            first = write_registry_match_review(**common, output_path=one)
            second = write_registry_match_review(**common, output_path=two)
            self.assertEqual(first, second)
            self.assertEqual(one.read_bytes(), two.read_bytes())

            cli_output = root / "cli.json"
            self.assertEqual(main([
                "build-registry-match-review",
                str(source_path),
                str(proposal_path),
                str(product_path),
                str(GOVERNED),
                str(TRACER / "local-data-bindings.json"),
                str(cli_output),
            ]), 0)
            self.assertEqual(cli_output.read_bytes(), one.read_bytes())


if __name__ == "__main__":
    unittest.main()
