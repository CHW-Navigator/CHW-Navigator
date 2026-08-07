from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from chw_navigator.canonical_bridge import CanonicalBridgeError, parse_reviewed_needs
from chw_navigator.registry_governance import ActivatedRegistryRelease
from chw_navigator.registry_match import build_registry_match_request, parse_registry_match_catalogue
from chw_navigator.synthetic_registry_pilot import (
    PILOT_WATERMARK,
    SyntheticRegistryPilotError,
    parse_synthetic_registry_pilot,
    parse_synthetic_registry_pilot_report,
    run_synthetic_registry_pilot,
    seal_synthetic_registry_pilot,
)
from chw_navigator.synthetic_registry_pilot_example import (
    _prompt_b_manual_digest,
    build_synthetic_registry_pilot_example,
    write_synthetic_registry_pilot_example,
)


ROOT = Path(__file__).resolve().parents[1]
PILOT_DIR = ROOT / "examples" / "pilot"
CATALOGUE_PATH = PILOT_DIR / "simulated-ministry-catalogue.json"
BLIND_PATH = PILOT_DIR / "independent-blind-candidates.json"
MATCH_PATH = PILOT_DIR / "independent-model-proposals.json"
MANUAL_PATH = PILOT_DIR / "clarified-mini-manuals.md"
EXPECTED_PATH = PILOT_DIR / "predeclared-expected-results.json"
MINISTRY_RESPONSE_PATH = PILOT_DIR / "simulated-ministry-response.md"
PILOT_NOTICE_PATH = PILOT_DIR / "PILOT-NO-CLINICAL-USE.txt"


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _build(**overrides):
    values = {
        "blind_evidence": _json(BLIND_PATH),
        "match_evidence": _json(MATCH_PATH),
        "manual_text": MANUAL_PATH.read_text(encoding="utf-8"),
        "expected_results": _json(EXPECTED_PATH),
        "ministry_response_text": MINISTRY_RESPONSE_PATH.read_text(encoding="utf-8"),
    }
    values.update(overrides)
    catalogue = parse_registry_match_catalogue(_json(CATALOGUE_PATH))
    return build_synthetic_registry_pilot_example(catalogue, **values)


def _pilot():
    return _build()


def _reseal(payload: dict):
    return parse_synthetic_registry_pilot(seal_synthetic_registry_pilot(payload))


def _rebind_case(payload: dict, case_index: int) -> None:
    case = payload["cases"][case_index]
    catalogue = parse_registry_match_catalogue(payload["catalogue"])
    request = build_registry_match_request(
        case["source_candidate"], catalogue, case["product_logic"], case["proposal"]["need_id"]
    )
    case["proposal"]["source_candidate_digest"] = request["source_candidate_digest"]
    case["proposal"]["catalogue_digest"] = request["catalogue_digest"]
    case["proposal"]["product_variables_digest"] = request["product_variables_digest"]
    case["proposal"]["product_binding_context_digest"] = request["product_binding_context_digest"]
    case["model_run"]["request_digest"] = _digest(request)
    case["model_run"]["response_digest"] = _digest(case["proposal"])


def _reseal_catalogue(payload: dict, changed_entry_index: int) -> None:
    catalogue = payload["catalogue"]
    entry = catalogue["entries"][changed_entry_index]
    projected = deepcopy(entry)
    projected.pop("projection_digest")
    entry["projection_digest"] = _digest(projected)
    raw = deepcopy(catalogue)
    raw.pop("content_digest")
    catalogue["content_digest"] = _digest(raw)
    for index in range(len(payload["cases"])):
        _rebind_case(payload, index)


class SyntheticRegistryPilotTests(unittest.TestCase):
    def test_standalone_pilot_catalogue_has_adjacent_no_clinical_use_notice(self) -> None:
        notice = PILOT_NOTICE_PATH.read_text(encoding="utf-8")
        self.assertTrue(notice.startswith("PILOT: NO CLINICAL USE\n"))
        self.assertIn("invented registry entries", notice)
        self.assertIn("not approved for", notice)

    def test_three_case_pilot_is_watermarked_e2_and_non_production(self) -> None:
        pilot = _pilot()
        report = run_synthetic_registry_pilot(pilot)
        self.assertEqual(report["overall_status"], "pilot_mechanics_passed")
        self.assertEqual(report["evidence_ceiling"], "E2")
        self.assertEqual(report["watermark"], PILOT_WATERMARK)
        self.assertTrue(report["pilot_only"])
        self.assertFalse(report["clinical_use_permitted"])
        self.assertFalse(report["deployment_permitted"])
        self.assertFalse(report["production_schema_compatible"])
        self.assertEqual(report["metrics"]["case_count"], 3)
        self.assertEqual(report["metrics"]["accepted_count"], 3)
        self.assertEqual(report["metrics"]["hidden_answer_mismatches_after_structural_unique_match"], 0)
        for case in report["cases"]:
            self.assertEqual(case["status"], "accepted_for_synthetic_pilot")
            self.assertEqual(case["model_run"]["run_kind"], "recorded_model_output")
            self.assertIsNone(case["model_run"]["generated_at"])
            self.assertFalse(case["model_run"]["request_payload_retained"])
            self.assertEqual(case["synthetic_review"]["decision"], "accepted_for_synthetic_pilot")
            self.assertFalse(case["synthetic_review"]["clinical_approval"])
            self.assertFalse(case["synthetic_review"]["deployment_authorization"])
            self.assertTrue(case["displayed_sources"])
            self.assertEqual(len(case["displayed_alternative_entries"]), 8)
            self.assertFalse(case["model_assessment"]["authoritative"])

    def test_sources_label_background_as_unverified_and_interfaces_as_synthetic(self) -> None:
        report = run_synthetic_registry_pilot(_pilot())
        for case in report["cases"]:
            statuses = {item["claim_status"] for item in case["displayed_sources"]}
            self.assertEqual(statuses, {"not_verified_in_run", "synthetic_assumption"})
            self.assertTrue(all(item["claim_supported"] and item["locator"] for item in case["displayed_sources"]))

    def test_builder_preserves_blinded_candidates_exactly_then_replays_matches(self) -> None:
        pilot = _pilot()
        blind = _json(BLIND_PATH)["raw_artifacts"]
        matched = _json(MATCH_PATH)["cases"]
        for case, blind_artifact, evidence in zip(pilot.cases, blind, matched, strict=True):
            self.assertEqual(case.source_candidate.model_dump(mode="json"), blind_artifact)
            self.assertEqual(case.source_candidate.model_dump(mode="json"), evidence["source_candidate"])
            self.assertEqual(case.proposal.model_dump(mode="json"), evidence["proposal"])
            self.assertEqual(case.model_run.request_digest, evidence["request_digest"])
            self.assertEqual(case.model_run.response_digest, evidence["response_digest"])

    def test_blinded_artifacts_contain_no_registry_entry_fields(self) -> None:
        artifacts = _json(BLIND_PATH)["raw_artifacts"]
        serialized = json.dumps(artifacts)
        self.assertNotIn('"entry_ref"', serialized)
        self.assertNotIn('"selected_entry_ref"', serialized)
        self.assertIn(
            "version_mismatch",
            _json(BLIND_PATH)["raw_artifacts"][1]["candidates"][0]["required_statuses"],
        )

    def test_every_blind_candidate_is_bound_to_the_complete_manual(self) -> None:
        evidence = _json(BLIND_PATH)
        manual_digest = _prompt_b_manual_digest(MANUAL_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            manual_digest,
            "01a19e7372a9fd5e28c93be8b5847cb12e9d920ce8e09ab71101c42c500141ec",
        )
        raw_file_digest = hashlib.sha256(MANUAL_PATH.read_bytes()).hexdigest()
        self.assertEqual(evidence["run_metadata"]["source_sha256"], raw_file_digest)
        self.assertNotEqual(manual_digest, raw_file_digest)
        for artifact in evidence["raw_artifacts"]:
            for candidate in artifact["candidates"]:
                self.assertEqual(candidate["provenance"]["source_digest"], manual_digest)

    def test_builder_rejects_changed_watermarks_and_candidate_stitching(self) -> None:
        blind = _json(BLIND_PATH)
        blind["watermark"]["clinical_use"] = True
        with self.assertRaisesRegex(SyntheticRegistryPilotError, "pilot restrictions"):
            _build(blind_evidence=blind)
        match = _json(MATCH_PATH)
        match["cases"][0]["source_candidate"]["candidates"][0]["problem"] += " altered"
        with self.assertRaisesRegex(SyntheticRegistryPilotError, "changed the registry-blind candidate"):
            _build(match_evidence=match)

    def test_manual_tamper_breaks_candidate_grounding(self) -> None:
        payload = _pilot().model_dump(mode="json")
        payload["cases"][0]["manual"]["text"] += " Changed after extraction."
        payload["cases"][0]["manual"]["content_digest"] = hashlib.sha256(
            payload["cases"][0]["manual"]["text"].encode("utf-8")
        ).hexdigest()
        with self.assertRaisesRegex(SyntheticRegistryPilotError, "pilot manual does not match the frozen"):
            run_synthetic_registry_pilot(_reseal(payload))

    def test_source_quote_must_remain_in_the_cited_section(self) -> None:
        payload = _pilot().model_dump(mode="json")
        case = payload["cases"][0]
        quote = case["source_candidate"]["candidates"][0]["source"]["quote"]
        case["manual"]["text"] = case["manual"]["text"].replace(quote, "Quote moved.") + "\n" + quote
        digest = hashlib.sha256(case["manual"]["text"].encode("utf-8")).hexdigest()
        case["manual"]["content_digest"] = digest
        case["source_candidate"]["candidates"][0]["provenance"]["source_digest"] = digest
        _rebind_case(payload, 0)
        with self.assertRaisesRegex(SyntheticRegistryPilotError, "pilot manual does not match the frozen"):
            run_synthetic_registry_pilot(_reseal(payload))

    def test_dropping_a_case_or_tampering_oracle_breaks_manifest(self) -> None:
        payload = _pilot().model_dump(mode="json")
        payload["cases"].pop()
        with self.assertRaisesRegex(SyntheticRegistryPilotError, "required-case manifest"):
            seal_synthetic_registry_pilot(payload)
        expected = _json(EXPECTED_PATH)
        expected["cases"][0]["expected_entry_ref"] = "pilot.local.person.estimated-date-of-birth@1.0.0"
        with self.assertRaisesRegex(SyntheticRegistryPilotError, "frozen pilot oracle"):
            _build(expected_results=expected)

    def test_frozen_oracle_binds_the_complete_catalogue_not_only_selected_entries(self) -> None:
        payload = _pilot().model_dump(mode="json")
        payload["catalogue"]["entries"].pop()
        raw = deepcopy(payload["catalogue"])
        raw.pop("content_digest")
        payload["catalogue"]["content_digest"] = _digest(raw)
        with self.assertRaisesRegex(SyntheticRegistryPilotError, "frozen expected-results"):
            seal_synthetic_registry_pilot(payload)

    def test_same_type_date_swap_is_caught_by_frozen_oracle(self) -> None:
        payload = _pilot().model_dump(mode="json")
        mappings = payload["cases"][1]["proposal"]["parameter_mappings"]
        birth = next(item for item in mappings if item["candidate_name"] == "birth_date")
        measured = next(item for item in mappings if item["candidate_name"] == "measurement_date")
        birth["variable_id"], measured["variable_id"] = measured["variable_id"], birth["variable_id"]
        _rebind_case(payload, 1)
        report = run_synthetic_registry_pilot(_reseal(payload))
        result = report["cases"][1]
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(report["metrics"]["hidden_answer_mismatches_after_structural_unique_match"], 1)
        self.assertEqual({x["check_id"]: x["status"] for x in result["checks"]}["pilot_parameter_mappings"], "fail")
        self.assertEqual(result["synthetic_review"]["decision"], "not_accepted")

    def test_same_shape_wrong_catalogue_entry_stops(self) -> None:
        payload = _pilot().model_dump(mode="json")
        case = payload["cases"][2]
        correct = case["proposal"]["selected_entry_ref"]
        wrong = "pilot.technical.calendar.bikram-sambat-elapsed-days-inclusive@0.1.0"
        case["proposal"]["selected_entry_ref"] = wrong
        next(item for item in case["proposal"]["alternatives"] if item["entry_ref"] == wrong)["entry_ref"] = correct
        _rebind_case(payload, 2)
        report = run_synthetic_registry_pilot(_reseal(payload))
        self.assertEqual(report["cases"][2]["status"], "stopped")
        self.assertEqual(report["metrics"]["hidden_answer_mismatches_after_structural_unique_match"], 1)

    def test_complete_catalogue_projection_not_just_root_is_frozen(self) -> None:
        payload = _pilot().model_dump(mode="json")
        index = next(i for i, e in enumerate(payload["catalogue"]["entries"]) if e["entry_ref"] == payload["cases"][0]["proposal"]["selected_entry_ref"])
        payload["catalogue"]["entries"][index]["local_read_contract"]["available_contexts"] = ["contact"]
        _reseal_catalogue(payload, index)
        with self.assertRaisesRegex(SyntheticRegistryPilotError, "pilot catalogue does not match the frozen"):
            _reseal(payload)

    def test_complete_product_variable_catalogue_is_frozen(self) -> None:
        payload = _pilot().model_dump(mode="json")
        sex = next(v for v in payload["cases"][1]["product_logic"]["variables"] if v["id"] == "v_sex")
        sex["domain"].append("unknown")
        _rebind_case(payload, 1)
        report = run_synthetic_registry_pilot(_reseal(payload))
        checks = {x["check_id"]: x["status"] for x in report["cases"][1]["checks"]}
        self.assertEqual(checks["pilot_product_variables"], "fail")

    def test_complete_binding_including_local_action_is_frozen(self) -> None:
        payload = _pilot().model_dump(mode="json")
        payload["cases"][0]["product_logic"]["local_action_ids"] = ["a_invented_but_valid"]
        payload["cases"][0]["proposal"]["local_action_id"] = "a_invented_but_valid"
        _rebind_case(payload, 0)
        report = run_synthetic_registry_pilot(_reseal(payload))
        checks = {x["check_id"]: x["status"] for x in report["cases"][0]["checks"]}
        self.assertEqual(checks["pilot_product_logic"], "fail")
        self.assertEqual(checks["pilot_complete_proposed_binding"], "fail")
        self.assertEqual(report["cases"][0]["status"], "stopped")

    def test_omitting_any_catalogue_alternative_stops_the_pilot(self) -> None:
        payload = _pilot().model_dump(mode="json")
        payload["cases"][1]["proposal"]["alternatives"].pop()
        _rebind_case(payload, 1)
        report = run_synthetic_registry_pilot(_reseal(payload))
        checks = {x["check_id"]: x["status"] for x in report["cases"][1]["checks"]}
        self.assertEqual(checks["pilot_complete_catalogue_comparison"], "fail")
        self.assertEqual(report["cases"][1]["status"], "stopped")

    def test_stale_product_binding_is_rejected_before_review(self) -> None:
        payload = _pilot().model_dump(mode="json")
        payload["cases"][0]["product_logic"]["variables"][0]["id"] = "v_different_date"
        with self.assertRaisesRegex(SyntheticRegistryPilotError, "request digest is stale"):
            run_synthetic_registry_pilot(_reseal(payload))

    def test_synthetic_reviewer_cannot_claim_approval_even_with_numeric_truth(self) -> None:
        for field in ("clinical_approval", "deployment_authorization"):
            for value in (True, 1):
                payload = _pilot().model_dump(mode="json")
                payload["cases"][0]["synthetic_reviewer"][field] = value
                with self.assertRaises(SyntheticRegistryPilotError):
                    seal_synthetic_registry_pilot(payload)

    def test_pilot_artifacts_are_rejected_by_production_contracts(self) -> None:
        pilot_payload = _pilot().model_dump(mode="json")
        report = run_synthetic_registry_pilot(_pilot())
        with self.assertRaises(CanonicalBridgeError):
            parse_reviewed_needs(report)
        with self.assertRaises(ValidationError):
            ActivatedRegistryRelease.model_validate(pilot_payload)

    def test_report_and_attestation_digests_detect_tampering(self) -> None:
        report = run_synthetic_registry_pilot(_pilot())
        changed = deepcopy(report)
        changed["cases"][0]["synthetic_review"]["decision"] = "not_accepted"
        raw = deepcopy(changed)
        raw.pop("content_digest")
        changed["content_digest"] = _digest(raw)
        with self.assertRaisesRegex(SyntheticRegistryPilotError, "attestation digest"):
            parse_synthetic_registry_pilot_report(changed)
        report["limitations"][0] = "Removed limitation"
        with self.assertRaisesRegex(SyntheticRegistryPilotError, "content digest"):
            parse_synthetic_registry_pilot_report(report)

    def test_resealed_but_contradictory_report_is_rejected(self) -> None:
        report = run_synthetic_registry_pilot(_pilot())
        report["metrics"]["accepted_count"] = 0
        report["metrics"]["stopped_count"] = 3
        report["metrics"]["accepted_fraction"] = 0
        raw = deepcopy(report)
        raw.pop("content_digest")
        report["content_digest"] = _digest(raw)
        with self.assertRaisesRegex(SyntheticRegistryPilotError, "metrics do not match"):
            parse_synthetic_registry_pilot_report(report)

    def test_all_catalogue_entries_are_pilot_namespaced_and_source_bound(self) -> None:
        catalogue = _json(CATALOGUE_PATH)
        response_digest = "sha256:" + hashlib.sha256(MINISTRY_RESPONSE_PATH.read_bytes()).hexdigest()
        self.assertEqual(len(catalogue["entries"]), 9)
        for entry in catalogue["entries"]:
            self.assertTrue(entry["entry_ref"].startswith("pilot."))
            synthetic = [s for s in entry["evidence_sources"] if s["claim_status"] == "synthetic_assumption"]
            self.assertTrue(synthetic)
            self.assertTrue(all(s["source_content_digest"] == response_digest for s in synthetic))
            source_descriptor = {
                "authoring_kind": "synthetic_catalogue_entry",
                "entry_ref": entry["entry_ref"],
                "ministry_response_digest": response_digest,
            }
            self.assertEqual(entry["source_entry_digest"], _digest(source_descriptor))
            if entry["kind"] == "local_data_read":
                self.assertNotIn("stale", entry["statuses"])

    def test_utf8_outputs_do_not_contain_mojibake(self) -> None:
        report = run_synthetic_registry_pilot(_pilot())
        self.assertNotIn("â", json.dumps(report, ensure_ascii=False))
        self.assertIn("—", report["watermark"])

    def test_written_example_is_byte_deterministic_and_minimal(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            report_a = write_synthetic_registry_pilot_example(CATALOGUE_PATH, first)
            report_b = write_synthetic_registry_pilot_example(CATALOGUE_PATH, second)
            self.assertEqual(report_a, report_b)
            expected = {"PILOT-ONLY.txt", "pilot-input.json", "pilot-report.json"}
            self.assertEqual({item.name for item in Path(first).iterdir()}, expected)
            for name in expected:
                self.assertEqual((Path(first) / name).read_bytes(), (Path(second) / name).read_bytes())


if __name__ == "__main__":
    unittest.main()
