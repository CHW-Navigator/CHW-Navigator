"""Isolated, source-backed registry-matching pilot.

This module deliberately cannot create production review, resolution, IR, CHT,
or deployment artifacts.  It replays recorded model proposals, re-evaluates
them from original inputs, applies a visibly synthetic review, and writes a
watermarked software-pilot report.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, model_validator

from .registry_match import (
    REGISTRY_MATCH_PROMPT,
    ProposedParameterMapping,
    RegistryBlindCandidateArtifact,
    RegistryMatchCatalogue,
    RegistryMatchError,
    RegistryMatchProposal,
    build_registry_match_request,
    evaluate_registry_match_proposal,
    parse_registry_match_catalogue,
    parse_registry_match_proposal,
)


PILOT_SCHEMA_VERSION = "synthetic-registry-pilot@1.0.0"
PILOT_REPORT_SCHEMA_VERSION = "synthetic-registry-pilot-report@1.0.0"
PILOT_EXPECTED_SCHEMA_VERSION = "synthetic-registry-pilot-expected@1.0.0"
PILOT_WATERMARK = "SYNTHETIC SOFTWARE PILOT ONLY — NOT FOR PATIENT CARE OR DEPLOYMENT"
PILOT_RESTRICTIONS = (
    "pilot_only",
    "non_clinical",
    "not_for_patient_care",
    "deployment_prohibited",
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SyntheticRegistryPilotError(ValueError):
    """Raised when the pilot inputs or replay evidence fail closed."""


class PilotManual(_StrictModel):
    document_id: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_b_source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def content_digest_matches_text(self) -> "PilotManual":
        actual = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if self.content_digest != actual:
            raise ValueError("pilot manual content digest does not match its exact UTF-8 text")
        return self


class PilotModelRun(_StrictModel):
    run_kind: Literal["recorded_model_output"]
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    generated_at: str | None
    prompt_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    request_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    response_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    temperature: float | None
    request_payload_retained: Literal[False]
    request_reproducible: Literal[True]
    response_payload_retained: Literal[True]
    limitations: tuple[str, ...] = Field(min_length=1)


class SyntheticReviewer(_StrictModel):
    review_kind: Literal["synthetic_role_play"]
    reviewer_id: str = Field(pattern=r"^synthetic-role-[a-z0-9_-]+$")
    review_scope: Literal["software_pipeline_mechanics_only"]
    clinical_approval: StrictBool
    deployment_authorization: StrictBool
    limitations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def cannot_claim_real_approval(self) -> "SyntheticReviewer":
        if self.clinical_approval or self.deployment_authorization:
            raise ValueError("synthetic reviewer cannot claim clinical or deployment approval")
        return self


class SyntheticReviewAttestation(SyntheticReviewer):
    content_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    decision: Literal["accepted_for_synthetic_pilot", "not_accepted"]
    reviewed_at: None
    source_candidate_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    catalogue_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    proposal_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_case_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    match_review_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def attestation_digest_matches(self) -> "SyntheticReviewAttestation":
        raw = self.model_dump(mode="json")
        actual = raw.pop("content_digest")
        if actual != _digest(raw):
            raise ValueError("synthetic review attestation digest does not match")
        return self


class PilotExpectedSemantics(_StrictModel):
    case_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    case_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    expected_outcome: Literal["unique_match", "ambiguous", "no_match", "needs_clarification"]
    expected_entry_ref: str | None = Field(
        default=None, pattern=r"^pilot\.[a-z][a-z0-9_.-]+@[0-9]+\.[0-9]+\.[0-9]+$"
    )
    expected_entry_projection_digest: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    expected_product_variables_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_product_logic_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_source_candidate_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_proposed_binding_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_parameter_mappings: tuple[ProposedParameterMapping, ...]

    @model_validator(mode="after")
    def expected_case_is_consistent(self) -> "PilotExpectedSemantics":
        mapping_keys = [
            (item.direction, item.candidate_name, item.registry_name, item.variable_id)
            for item in self.expected_parameter_mappings
        ]
        if len(mapping_keys) != len(set(mapping_keys)):
            raise ValueError("pilot expected mappings must be unique")
        if self.expected_outcome == "unique_match":
            if self.expected_entry_ref is None or self.expected_entry_projection_digest is None:
                raise ValueError("unique expected outcome requires an entry and projection digest")
        elif self.expected_entry_ref is not None or self.expected_entry_projection_digest is not None:
            raise ValueError("non-unique expected outcomes cannot select an entry")
        raw = self.model_dump(mode="json")
        actual = raw.pop("case_digest")
        if actual != _digest(raw):
            raise ValueError("pilot expected-case digest does not match")
        return self


class PilotExpectedResults(_StrictModel):
    schema_version: Literal[PILOT_EXPECTED_SCHEMA_VERSION]
    content_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    watermark: Literal[PILOT_WATERMARK]
    authoring_kind: Literal["synthetic_predeclared_test_oracle"]
    frozen_before_registry_match_run: Literal[True]
    clinical_use_permitted: Literal[False]
    deployment_permitted: Literal[False]
    expected_catalogue_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_manual_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_ministry_response_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_match_prompt_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_blind_artifacts_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    cases: tuple[PilotExpectedSemantics, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def digest_and_cases_are_valid(self) -> "PilotExpectedResults":
        ids = [item.case_id for item in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("pilot expected-result case IDs must be unique")
        raw = self.model_dump(mode="json")
        actual = raw.pop("content_digest")
        if actual != _digest(raw):
            raise ValueError("pilot expected-results digest does not match")
        return self


class SyntheticPilotCase(_StrictModel):
    case_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    manual: PilotManual
    source_candidate: RegistryBlindCandidateArtifact
    product_logic: dict[str, Any]
    proposal: RegistryMatchProposal
    model_run: PilotModelRun
    synthetic_reviewer: SyntheticReviewer


class SyntheticRegistryPilot(_StrictModel):
    schema_version: Literal[PILOT_SCHEMA_VERSION]
    content_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    pilot_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    watermark: Literal[PILOT_WATERMARK]
    pilot_only: Literal[True]
    clinical_use_permitted: Literal[False]
    deployment_permitted: Literal[False]
    use_restrictions: tuple[str, ...]
    ministry_response_kind: Literal["simulated_for_software_pilot"]
    catalogue: RegistryMatchCatalogue
    expected_results: PilotExpectedResults
    required_case_ids: tuple[str, ...] = Field(min_length=1)
    cases: tuple[SyntheticPilotCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def restrictions_and_cases_are_complete(self) -> "SyntheticRegistryPilot":
        if tuple(self.use_restrictions) != PILOT_RESTRICTIONS:
            raise ValueError("pilot use restrictions must use the complete ordered safety set")
        case_ids = [item.case_id for item in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("pilot case IDs must be unique")
        if len(self.required_case_ids) != len(set(self.required_case_ids)):
            raise ValueError("required pilot case IDs must be unique")
        if tuple(case_ids) != tuple(self.required_case_ids):
            raise ValueError("pilot cases must exactly cover the ordered required-case manifest")
        if tuple(case_ids) != tuple(item.case_id for item in self.expected_results.cases):
            raise ValueError("pilot cases must exactly match the frozen expected-results artifact")
        if self.catalogue.content_digest != self.expected_results.expected_catalogue_digest:
            raise ValueError("pilot catalogue does not match the frozen expected-results artifact")
        if any(
            case.manual.content_digest != self.expected_results.expected_manual_digest
            for case in self.cases
        ):
            raise ValueError("pilot manual does not match the frozen expected-results artifact")
        if self.expected_results.expected_match_prompt_digest != _digest(REGISTRY_MATCH_PROMPT):
            raise ValueError("registry-match prompt does not match the frozen expected-results artifact")
        blind_digest = _digest([
            case.source_candidate.model_dump(mode="json") for case in self.cases
        ])
        if blind_digest != self.expected_results.expected_blind_artifacts_digest:
            raise ValueError("blinded artifacts do not match the frozen expected-results artifact")
        if any(not entry.entry_ref.startswith("pilot.") for entry in self.catalogue.entries):
            raise ValueError("synthetic pilot catalogue entries must use the pilot namespace")
        if any(
            not any(source.claim_status == "synthetic_assumption" for source in entry.evidence_sources)
            for entry in self.catalogue.entries
        ):
            raise ValueError("every synthetic pilot catalogue entry must identify its synthetic source")
        if any(len(case.source_candidate.candidates) != 1 for case in self.cases):
            raise ValueError("each pilot case must contain exactly one blinded candidate")
        candidate_ids = [
            candidate.local_id
            for case in self.cases
            for candidate in case.source_candidate.candidates
        ]
        proposal_ids = [case.proposal.need_id for case in self.cases]
        if len(candidate_ids) != len(self.cases) or sorted(candidate_ids) != sorted(proposal_ids):
            raise ValueError("pilot must contain exactly one proposal for every blinded candidate")
        return self


class PilotCaseResult(_StrictModel):
    case_id: str
    status: Literal["accepted_for_synthetic_pilot", "stopped"]
    selected_entry_ref: str | None
    match_review_digest: str | None
    checks: tuple[dict[str, str], ...]
    displayed_sources: tuple[dict[str, Any], ...]
    displayed_alternative_entries: tuple[dict[str, Any], ...]
    alternatives: tuple[dict[str, Any], ...]
    parameter_mappings: tuple[dict[str, str], ...]
    model_assessment: dict[str, Any]
    model_run: PilotModelRun
    synthetic_review: SyntheticReviewAttestation


class PilotMetrics(_StrictModel):
    case_count: int = Field(ge=1)
    accepted_count: int = Field(ge=0)
    stopped_count: int = Field(ge=0)
    accepted_fraction: float = Field(ge=0, le=1)
    hidden_answer_mismatches_after_structural_unique_match: int = Field(ge=0)


class SyntheticRegistryPilotReport(_StrictModel):
    schema_version: Literal[PILOT_REPORT_SCHEMA_VERSION]
    content_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    pilot_input_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    pilot_id: str
    watermark: Literal[PILOT_WATERMARK]
    pilot_only: Literal[True]
    clinical_use_permitted: Literal[False]
    deployment_permitted: Literal[False]
    production_schema_compatible: Literal[False]
    evidence_ceiling: Literal["E2"]
    overall_status: Literal["pilot_mechanics_passed", "pilot_stopped"]
    metrics: PilotMetrics
    cases: tuple[PilotCaseResult, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def result_counts_and_decisions_are_consistent(self) -> "SyntheticRegistryPilotReport":
        accepted = sum(case.status == "accepted_for_synthetic_pilot" for case in self.cases)
        stopped = len(self.cases) - accepted
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("pilot report case IDs must be unique")
        if (
            self.metrics.case_count != len(self.cases)
            or self.metrics.accepted_count != accepted
            or self.metrics.stopped_count != stopped
            or self.metrics.accepted_fraction != accepted / len(self.cases)
        ):
            raise ValueError("pilot report metrics do not match its cases")
        if (self.overall_status == "pilot_mechanics_passed") != (stopped == 0):
            raise ValueError("pilot report overall status does not match its cases")
        for case in self.cases:
            accepted_case = case.status == "accepted_for_synthetic_pilot"
            if accepted_case != (case.synthetic_review.decision == "accepted_for_synthetic_pilot"):
                raise ValueError("pilot case status does not match its synthetic attestation")
            if case.match_review_digest != case.synthetic_review.match_review_digest:
                raise ValueError("pilot case does not bind its synthetic attestation")
            if accepted_case and (case.selected_entry_ref is None or case.match_review_digest is None):
                raise ValueError("accepted pilot case requires a selected entry and review digest")
        return self


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _seal(payload: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(payload)
    result.pop("content_digest", None)
    result["content_digest"] = _digest(result)
    return result


def seal_synthetic_registry_pilot(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(payload)
    normalized["content_digest"] = "sha256:" + "0" * 64
    try:
        normalized = SyntheticRegistryPilot.model_validate(normalized).model_dump(mode="json")
    except ValidationError as exc:
        raise SyntheticRegistryPilotError(f"invalid synthetic registry pilot: {exc}") from exc
    return _seal(normalized)


def parse_synthetic_registry_pilot(payload: Any) -> SyntheticRegistryPilot:
    try:
        parsed = SyntheticRegistryPilot.model_validate(payload)
    except ValidationError as exc:
        raise SyntheticRegistryPilotError(f"invalid synthetic registry pilot: {exc}") from exc
    raw = parsed.model_dump(mode="json")
    expected = raw.pop("content_digest")
    if expected != _digest(raw):
        raise SyntheticRegistryPilotError("synthetic registry pilot content digest does not match")
    try:
        parse_registry_match_catalogue(parsed.catalogue.model_dump(mode="json"))
    except RegistryMatchError as exc:
        raise SyntheticRegistryPilotError(f"invalid pilot catalogue: {exc}") from exc
    return parsed


def parse_synthetic_registry_pilot_report(payload: Any) -> SyntheticRegistryPilotReport:
    try:
        parsed = SyntheticRegistryPilotReport.model_validate(payload)
    except ValidationError as exc:
        raise SyntheticRegistryPilotError(f"invalid synthetic registry pilot report: {exc}") from exc
    raw = parsed.model_dump(mode="json")
    expected = raw.pop("content_digest")
    if expected != _digest(raw):
        raise SyntheticRegistryPilotError("synthetic registry pilot report content digest does not match")
    return parsed


def _verify_candidate_grounding(case: SyntheticPilotCase) -> None:
    candidate = case.source_candidate.candidates[0]
    if candidate.provenance.source_digest != case.manual.prompt_b_source_digest:
        raise SyntheticRegistryPilotError(
            f"{case.case_id}: candidate does not bind the complete normalized Prompt B manual"
        )
    if candidate.source.document_id != case.manual.document_id:
        raise SyntheticRegistryPilotError(f"{case.case_id}: cited document ID does not match the manual")
    heading = re.escape(candidate.source.section)
    section_match = re.search(
        rf"(?ms)^##[ \t]+{heading}[ \t]*\r?\n(?P<body>.*?)(?=^##[ \t]+|\Z)",
        case.manual.text,
    )
    if section_match is None:
        raise SyntheticRegistryPilotError(f"{case.case_id}: cited section does not exist in the manual")
    if candidate.source.quote not in section_match.group("body"):
        raise SyntheticRegistryPilotError(f"{case.case_id}: source quote is not grounded at its cited location")
    if candidate.source.page != "1":
        raise SyntheticRegistryPilotError(
            f"{case.case_id}: cited page does not match the normalized Prompt B manual"
        )


def _verify_semantics(
    case: SyntheticPilotCase,
    expected: PilotExpectedSemantics,
    review: dict[str, Any],
    product_variables_digest: str,
    catalogue_entry_refs: set[str],
) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    selected = review.get("selected_entry")

    def exact(check_id: str, actual: Any, required: Any, message: str) -> None:
        checks.append({
            "check_id": check_id,
            "status": "pass" if actual == required else "fail",
            "message": message,
        })

    exact("pilot_expected_outcome", review.get("outcome"), expected.expected_outcome, "Match outcome equals the frozen pilot oracle.")
    exact("pilot_product_variables", product_variables_digest, expected.expected_product_variables_digest, "The complete ordered Product-variable catalogue equals the frozen pilot oracle.")
    exact("pilot_product_logic", _digest(case.product_logic), expected.expected_product_logic_digest, "The full Product logic supplied to the matcher, including allowed local action IDs, equals the frozen pilot oracle.")
    exact("pilot_source_candidate", review.get("source_candidate_digest"), expected.expected_source_candidate_digest, "The registry-blind candidate equals the frozen pilot oracle.")
    if expected.expected_outcome == "unique_match":
        if not isinstance(selected, dict):
            checks.append({"check_id": "pilot_selected_entry", "status": "fail", "message": "The frozen oracle requires a selected entry."})
            return checks
        exact("pilot_expected_entry", selected.get("entry_ref"), expected.expected_entry_ref, "Selected entry matches the frozen pilot oracle.")
        exact(
            "pilot_complete_entry_projection",
            selected.get("projection_digest"),
            expected.expected_entry_projection_digest,
            "The complete selected entry projection, including statuses, value semantics, contexts, reference data, and sources, matches the frozen pilot oracle.",
        )
    else:
        exact("pilot_no_selected_entry", selected, None, "A non-unique expected outcome does not select an entry.")
    actual_mappings = [item.model_dump(mode="json") for item in case.proposal.parameter_mappings]
    expected_mappings = [item.model_dump(mode="json") for item in expected.expected_parameter_mappings]
    mapping_key = lambda item: (item["direction"], item["registry_name"], item["candidate_name"], item["variable_id"])
    exact(
        "pilot_parameter_mappings",
        sorted(actual_mappings, key=mapping_key),
        sorted(expected_mappings, key=mapping_key),
        "Parameter and Product-variable mappings match the frozen pilot oracle exactly.",
    )
    exact(
        "pilot_complete_proposed_binding",
        _digest(review.get("proposed_binding")),
        expected.expected_proposed_binding_digest,
        "The complete proposed binding, including action, status, and failure fields, matches the frozen pilot oracle.",
    )
    selected_ref = review.get("selected_entry", {}).get("entry_ref") if isinstance(review.get("selected_entry"), dict) else None
    expected_alternatives = catalogue_entry_refs - ({selected_ref} if selected_ref else set())
    actual_alternatives = {item.entry_ref for item in case.proposal.alternatives}
    exact(
        "pilot_complete_catalogue_comparison",
        actual_alternatives,
        expected_alternatives,
        "The model assessed every unselected catalogue entry, including every same-shape decoy.",
    )
    exact(
        "pilot_confidence_display",
        review.get("model_assessment", {}).get("self_reported_threshold_display"),
        "threshold_met",
        "The exhaustive, non-authoritative confidence display meets this pilot's predeclared review rule.",
    )
    return checks


def run_synthetic_registry_pilot(pilot: SyntheticRegistryPilot) -> dict[str, Any]:
    """Replay and score a pilot. No output from this function is production-compatible."""
    pilot = parse_synthetic_registry_pilot(pilot.model_dump(mode="json"))
    catalogue = parse_registry_match_catalogue(pilot.catalogue.model_dump(mode="json"))
    entries_by_ref = {item.entry_ref: item for item in catalogue.entries}
    expected_by_case = {item.case_id: item for item in pilot.expected_results.cases}
    results: list[dict[str, Any]] = []
    accepted = 0
    observed_false_unique = 0
    for case in pilot.cases:
        _verify_candidate_grounding(case)
        source_candidate = case.source_candidate.model_dump(mode="json")
        proposal = parse_registry_match_proposal(case.proposal.model_dump(mode="json"))
        request = build_registry_match_request(
            source_candidate, catalogue, case.product_logic, proposal.need_id
        )
        run = case.model_run
        if run.prompt_digest != _digest(REGISTRY_MATCH_PROMPT):
            raise SyntheticRegistryPilotError(f"{case.case_id}: model run prompt digest is stale")
        if run.request_digest != _digest(request):
            raise SyntheticRegistryPilotError(f"{case.case_id}: model run request digest is stale")
        if run.response_digest != _digest(proposal.model_dump(mode="json")):
            raise SyntheticRegistryPilotError(f"{case.case_id}: model run response digest is stale")
        try:
            review = evaluate_registry_match_proposal(
                source_candidate, proposal, catalogue, case.product_logic
            )
        except RegistryMatchError as exc:
            raise SyntheticRegistryPilotError(f"{case.case_id}: deterministic match review failed: {exc}") from exc
        expected = expected_by_case[case.case_id]
        pilot_checks = _verify_semantics(
            case, expected, review, request["product_variables_digest"], set(entries_by_ref)
        )
        all_checks = [*review["checks"], *pilot_checks]
        stopped = (
            review["outcome"] != "unique_match"
            or any(item["status"] in {"fail", "needs_clarification"} for item in all_checks)
        )
        if review["outcome"] == "unique_match" and any(
            item["check_id"].startswith("pilot_") and item["status"] == "fail"
            for item in pilot_checks
        ):
            observed_false_unique += 1
        status = "pilot_stopped" if stopped else "accepted_for_synthetic_pilot"
        if not stopped:
            accepted += 1
        selected = review.get("selected_entry") or {}
        attestation_payload = {
            "review_kind": case.synthetic_reviewer.review_kind,
            "reviewer_id": case.synthetic_reviewer.reviewer_id,
            "review_scope": case.synthetic_reviewer.review_scope,
            "clinical_approval": False,
            "deployment_authorization": False,
            "limitations": list(case.synthetic_reviewer.limitations),
            "content_digest": "sha256:" + "0" * 64,
            "decision": "not_accepted" if stopped else "accepted_for_synthetic_pilot",
            "reviewed_at": None,
            "source_candidate_digest": review["source_candidate_digest"],
            "catalogue_digest": review["catalogue_digest"],
            "proposal_digest": review["proposal_digest"],
            "expected_case_digest": expected.case_digest,
            "match_review_digest": review["content_digest"],
        }
        attestation = SyntheticReviewAttestation.model_validate(
            _seal(attestation_payload)
        ).model_dump(mode="json")
        results.append({
            "case_id": case.case_id,
            "status": "stopped" if stopped else status,
            "selected_entry_ref": selected.get("entry_ref"),
            "match_review_digest": review.get("content_digest"),
            "checks": all_checks,
            "displayed_sources": selected.get("evidence_sources", []),
            "displayed_alternative_entries": [
                entries_by_ref[item.entry_ref].model_dump(mode="json")
                for item in proposal.alternatives
            ],
            "alternatives": review["alternatives"],
            "parameter_mappings": review["parameter_mappings"],
            "model_assessment": review["model_assessment"],
            "model_run": run.model_dump(mode="json"),
            "synthetic_review": attestation,
        })
    total = len(pilot.cases)
    report = {
        "schema_version": PILOT_REPORT_SCHEMA_VERSION,
        "content_digest": "sha256:" + "0" * 64,
        "pilot_input_digest": pilot.content_digest,
        "pilot_id": pilot.pilot_id,
        "watermark": PILOT_WATERMARK,
        "pilot_only": True,
        "clinical_use_permitted": False,
        "deployment_permitted": False,
        "production_schema_compatible": False,
        "evidence_ceiling": "E2",
        "overall_status": "pilot_mechanics_passed" if accepted == total else "pilot_stopped",
        "metrics": {
            "case_count": total,
            "accepted_count": accepted,
            "stopped_count": total - accepted,
            "accepted_fraction": accepted / total,
            "hidden_answer_mismatches_after_structural_unique_match": observed_false_unique,
        },
        "cases": results,
        "limitations": [
            "The Ministry response, reviewers, catalogue entries, implementations, and reference-data digests are simulated.",
            "Real WHO and CHT sources support background claims only; they do not approve the invented interfaces.",
            "This replay tests matching mechanics, not clinical calculations, CHT execution, or deployment safety.",
            "Recorded model outputs are E2 evidence at most and do not establish live-model reliability.",
            "The blindness and oracle ordering are a recorded task procedure, not independently timestamped proof.",
            "All three expected cases are positive matches; this run does not estimate no-match or ambiguity reliability.",
            "The production governed capability schema cannot yet project all pilot reference-data and parameter semantics.",
        ],
    }
    sealed = _seal(report)
    return parse_synthetic_registry_pilot_report(sealed).model_dump(mode="json")


def write_synthetic_registry_pilot_report(input_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    source = Path(input_path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SyntheticRegistryPilotError(f"could not load synthetic pilot {source}: {exc}") from exc
    pilot = parse_synthetic_registry_pilot(payload)
    report = run_synthetic_registry_pilot(pilot)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
