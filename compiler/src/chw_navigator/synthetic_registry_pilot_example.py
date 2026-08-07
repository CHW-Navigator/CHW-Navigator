"""Build the isolated pilot from retained blinded and registry-visible evidence."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from pydantic import ValidationError

from .registry_match import (
    REGISTRY_MATCH_PROMPT,
    RegistryBlindCandidateArtifact,
    RegistryMatchCatalogue,
    RegistryMatchError,
    build_registry_match_request,
    parse_registry_match_catalogue,
    parse_registry_match_proposal,
)
from .synthetic_registry_pilot import (
    PILOT_RESTRICTIONS,
    PILOT_SCHEMA_VERSION,
    PILOT_WATERMARK,
    PilotExpectedResults,
    SyntheticRegistryPilot,
    SyntheticRegistryPilotError,
    parse_synthetic_registry_pilot,
    run_synthetic_registry_pilot,
    seal_synthetic_registry_pilot,
)


_EXAMPLE_DIR = Path(__file__).resolve().parents[2] / "examples" / "pilot"
_EXPECTED_CASE_IDS = ("dob_local_read", "who_height_for_age", "nepali_elapsed_days")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _source_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _prompt_b_manual_digest(text: str) -> str:
    """Reproduce Product Prompt B's digest for the complete normalized manual."""
    sections = [
        {
            "page": "1",
            "section": match.group("section").strip(),
            "text": match.group("text").strip(),
        }
        for match in re.finditer(
            r"(?ms)^##[ \t]+(?P<section>.+?)[ \t]*\r?\n(?P<text>.*?)(?=^##[ \t]+|\Z)",
            text,
        )
    ]
    if not sections:
        raise SyntheticRegistryPilotError("mini-manual has no Prompt B sections")
    return hashlib.sha256(_canonical_json({
        "document_id": "clarified-mini-manuals.md",
        "sections": sections,
    })).hexdigest()


def _reviewer(case_id: str) -> dict[str, Any]:
    """Describe a synthetic reviewer; the runner creates the decision afterwards."""
    return {
        "review_kind": "synthetic_role_play",
        "reviewer_id": f"synthetic-role-{case_id}",
        "review_scope": "software_pipeline_mechanics_only",
        "clinical_approval": False,
        "deployment_authorization": False,
        "limitations": [
            "The reviewer is simulated and is not a clinician or Ministry approver.",
            "The runner, not this descriptor, records whether software-only pilot checks passed.",
        ],
    }


def _validate_blind_evidence(
    evidence: dict[str, Any], manual_text: str
) -> tuple[dict[str, Any], ...]:
    watermark = evidence.get("watermark")
    if not isinstance(watermark, dict) or (
        watermark.get("synthetic") is not True
        or watermark.get("clinical_use") is not False
        or watermark.get("deployment_use") is not False
    ):
        raise SyntheticRegistryPilotError("blinded evidence lacks the required pilot restrictions")
    metadata = evidence.get("run_metadata")
    if not isinstance(metadata, dict) or metadata.get("mode") != "registry-blind":
        raise SyntheticRegistryPilotError("blinded evidence must identify a registry-blind run")
    expected_source_digest = _source_digest(manual_text)
    if metadata.get("source_sha256") != expected_source_digest:
        raise SyntheticRegistryPilotError("blinded evidence is bound to a different mini-manual")
    if metadata.get("source_path") != "compiler/examples/pilot/clarified-mini-manuals.md":
        raise SyntheticRegistryPilotError("blinded evidence identifies an unexpected source path")
    retention = evidence.get("retention_flags")
    if not isinstance(retention, dict) or (
        retention.get("raw_artifacts_retained") is not True
        or retention.get("source_quotes_retained") is not True
        or retention.get("registry_context_retained") is not False
    ):
        raise SyntheticRegistryPilotError("blinded evidence retention flags are incomplete")
    artifacts = evidence.get("raw_artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != len(_EXPECTED_CASE_IDS):
        raise SyntheticRegistryPilotError("blinded evidence must contain exactly three raw artifacts")
    if re.search(r'"(?:selected_entry_ref|entry_ref)"', json.dumps(artifacts)):
        raise SyntheticRegistryPilotError("registry-blind artifacts must not contain registry entry fields")
    try:
        parsed_artifacts = tuple(
            RegistryBlindCandidateArtifact.model_validate(item) for item in artifacts
        )
    except ValidationError as exc:
        raise SyntheticRegistryPilotError(f"invalid registry-blind artifact: {exc}") from exc
    prompt_b_source_digest = _prompt_b_manual_digest(manual_text)
    for artifact in parsed_artifacts:
        for candidate in artifact.candidates:
            if candidate.provenance.source_digest != prompt_b_source_digest:
                raise SyntheticRegistryPilotError(
                    "every registry-blind candidate must be bound to the complete normalized Prompt B manual"
                )
    return tuple(deepcopy(item) for item in artifacts)


def _validate_match_evidence(
    evidence: dict[str, Any], catalogue: RegistryMatchCatalogue
) -> tuple[dict[str, Any], ...]:
    watermark = evidence.get("pilot_watermark")
    if not isinstance(watermark, dict) or (
        watermark.get("classification") != "SYNTHETIC_SOFTWARE_PILOT_ONLY"
        or watermark.get("clinical_use") != "PROHIBITED"
        or watermark.get("deployment_authorization") != "NONE"
    ):
        raise SyntheticRegistryPilotError("independent match evidence lacks the required pilot restrictions")
    model_evidence = evidence.get("model_run")
    if not isinstance(model_evidence, dict) or (
        not isinstance(model_evidence.get("agent_identity"), str)
        or not model_evidence.get("agent_identity")
        or not isinstance(model_evidence.get("provider_surface"), str)
        or not model_evidence.get("provider_surface")
        or model_evidence.get("exact_serving_model_available") is not False
        or model_evidence.get("exact_serving_model") is not None
    ):
        raise SyntheticRegistryPilotError("independent model identity metadata is missing or inconsistent")
    if evidence.get("request_payload_retained") is not False:
        raise SyntheticRegistryPilotError("match evidence must state that original requests were not retained")
    if evidence.get("catalogue_digest") != catalogue.content_digest:
        raise SyntheticRegistryPilotError("independent match evidence is bound to a different catalogue")
    cases = evidence.get("cases")
    if not isinstance(cases, list):
        raise SyntheticRegistryPilotError("independent match evidence requires a cases array")
    if tuple(item.get("case_id") for item in cases if isinstance(item, dict)) != _EXPECTED_CASE_IDS:
        raise SyntheticRegistryPilotError("independent match evidence does not cover the required cases exactly")
    return tuple(cases)


def _validate_catalogue_sources(catalogue: RegistryMatchCatalogue, ministry_response_text: str) -> None:
    response_digest = "sha256:" + _source_digest(ministry_response_text)
    heading_fragments = {
        re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
        for heading in re.findall(r"(?m)^##[ \t]+(.+?)[ \t]*$", ministry_response_text)
    }
    for entry in catalogue.entries:
        synthetic = [source for source in entry.evidence_sources if source.claim_status == "synthetic_assumption"]
        if not synthetic:
            raise SyntheticRegistryPilotError(f"{entry.entry_ref}: missing synthetic Ministry source")
        if any(source.source_content_digest != response_digest for source in synthetic):
            raise SyntheticRegistryPilotError(f"{entry.entry_ref}: synthetic source digest is stale")
        for source in synthetic:
            fragment = source.locator.rsplit("#", 1)[-1] if "#" in source.locator else ""
            if fragment not in heading_fragments:
                raise SyntheticRegistryPilotError(
                    f"{entry.entry_ref}: synthetic source locator has no matching heading"
                )
        expected_source_entry_digest = _digest({
            "authoring_kind": "synthetic_catalogue_entry",
            "entry_ref": entry.entry_ref,
            "ministry_response_digest": response_digest,
        })
        if entry.source_entry_digest != expected_source_entry_digest:
            raise SyntheticRegistryPilotError(
                f"{entry.entry_ref}: synthetic source-entry digest does not reproduce"
            )


def build_synthetic_registry_pilot_example(
    catalogue: RegistryMatchCatalogue,
    *,
    blind_evidence: dict[str, Any],
    match_evidence: dict[str, Any],
    manual_text: str,
    expected_results: dict[str, Any],
    ministry_response_text: str,
) -> SyntheticRegistryPilot:
    """Bind independent extraction, independent matching, and a predeclared oracle."""
    catalogue = parse_registry_match_catalogue(catalogue.model_dump(mode="json"))
    blind_artifacts = _validate_blind_evidence(blind_evidence, manual_text)
    match_cases = _validate_match_evidence(match_evidence, catalogue)
    _validate_catalogue_sources(catalogue, ministry_response_text)
    try:
        frozen_expected = PilotExpectedResults.model_validate(expected_results)
    except ValidationError as exc:
        raise SyntheticRegistryPilotError(f"invalid frozen pilot oracle: {exc}") from exc
    if frozen_expected.expected_ministry_response_digest != "sha256:" + _source_digest(ministry_response_text):
        raise SyntheticRegistryPilotError("Ministry response does not match the frozen pilot oracle")

    manual_digest = _source_digest(manual_text)
    prompt_b_manual_digest = _prompt_b_manual_digest(manual_text)
    prompt_digest = _digest(REGISTRY_MATCH_PROMPT)
    model_evidence = match_evidence["model_run"]
    cases: list[dict[str, Any]] = []
    for case_id, blind_artifact, evidence in zip(
        _EXPECTED_CASE_IDS, blind_artifacts, match_cases, strict=True
    ):
        source_candidate = deepcopy(evidence.get("source_candidate"))
        if source_candidate != blind_artifact:
            raise SyntheticRegistryPilotError(
                f"{case_id}: registry-visible matcher changed the registry-blind candidate"
            )
        proposal = parse_registry_match_proposal(evidence["proposal"]).model_dump(mode="json")
        product_logic = deepcopy(evidence["product_logic"])
        request = build_registry_match_request(
            source_candidate, catalogue, product_logic, proposal["need_id"]
        )
        if evidence.get("request_digest") != _digest(request):
            raise SyntheticRegistryPilotError(f"{case_id}: retained request digest does not reproduce")
        if evidence.get("response_digest") != _digest(proposal):
            raise SyntheticRegistryPilotError(f"{case_id}: retained response digest does not reproduce")
        candidate = source_candidate["candidates"][0]
        if candidate["provenance"]["source_digest"] != prompt_b_manual_digest:
            raise SyntheticRegistryPilotError(
                f"{case_id}: candidate is not bound to the complete normalized Prompt B manual"
            )
        cases.append({
            "case_id": case_id,
            "manual": {
                "document_id": candidate["source"]["document_id"],
                "source_path": "compiler/examples/pilot/clarified-mini-manuals.md",
                "content_digest": manual_digest,
                "prompt_b_source_digest": prompt_b_manual_digest,
                "text": manual_text,
            },
            "source_candidate": source_candidate,
            "product_logic": product_logic,
            "proposal": proposal,
            "model_run": {
                "run_kind": "recorded_model_output",
                "provider": model_evidence["provider_surface"],
                "model": "exact serving model/build unavailable",
                "run_id": f"{model_evidence['agent_identity']}:{case_id}",
                "generated_at": None,
                "prompt_digest": prompt_digest,
                "request_digest": evidence["request_digest"],
                "response_digest": evidence["response_digest"],
                "temperature": None,
                "request_payload_retained": False,
                "request_reproducible": True,
                "response_payload_retained": True,
                "limitations": [
                    "The exact serving model/build, temperature, and timestamp were unavailable.",
                    "The original request payload was not retained; it is reproducible from retained inputs.",
                ],
            },
            "synthetic_reviewer": _reviewer(case_id),
        })
    raw = {
        "schema_version": PILOT_SCHEMA_VERSION,
        "content_digest": "sha256:" + "0" * 64,
        "pilot_id": "registry_match_three_case_software_pilot",
        "watermark": PILOT_WATERMARK,
        "pilot_only": True,
        "clinical_use_permitted": False,
        "deployment_permitted": False,
        "use_restrictions": list(PILOT_RESTRICTIONS),
        "ministry_response_kind": "simulated_for_software_pilot",
        "catalogue": catalogue.model_dump(mode="json"),
        "expected_results": frozen_expected.model_dump(mode="json"),
        "required_case_ids": list(_EXPECTED_CASE_IDS),
        "cases": cases,
    }
    return parse_synthetic_registry_pilot(seal_synthetic_registry_pilot(raw))


def write_synthetic_registry_pilot_example(
    catalogue_path: str | Path, output_dir: str | Path
) -> dict[str, Any]:
    catalogue_source = Path(catalogue_path)
    try:
        catalogue = parse_registry_match_catalogue(json.loads(catalogue_source.read_text(encoding="utf-8")))
        blind = json.loads((_EXAMPLE_DIR / "independent-blind-candidates.json").read_text(encoding="utf-8"))
        match = json.loads((_EXAMPLE_DIR / "independent-model-proposals.json").read_text(encoding="utf-8"))
        expected = json.loads((_EXAMPLE_DIR / "predeclared-expected-results.json").read_text(encoding="utf-8"))
        manual_text = (_EXAMPLE_DIR / "clarified-mini-manuals.md").read_text(encoding="utf-8")
        ministry_text = (_EXAMPLE_DIR / "simulated-ministry-response.md").read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError, RegistryMatchError) as exc:
        raise SyntheticRegistryPilotError(f"could not load synthetic pilot evidence: {exc}") from exc
    pilot = build_synthetic_registry_pilot_example(
        catalogue,
        blind_evidence=blind,
        match_evidence=match,
        manual_text=manual_text,
        expected_results=expected,
        ministry_response_text=ministry_text,
    )
    report = run_synthetic_registry_pilot(pilot)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "PILOT-ONLY.txt").write_text(PILOT_WATERMARK + "\n", encoding="utf-8")
    (output / "pilot-input.json").write_text(
        json.dumps(pilot.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "pilot-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report
