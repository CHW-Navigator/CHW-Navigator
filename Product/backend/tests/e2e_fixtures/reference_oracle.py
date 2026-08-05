"""Independent behavior oracle for the synthetic fixture corpus.

The oracle is test-only.  It consumes raw case inputs and never receives a
generated clinical artifact.  A later end-to-end adapter can normalize an
artifact's result and compare it with this result without supplying derived
predicates such as ``p_fast_breathing`` in the patient input.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from backend.operational import (
    build_external_effect_package,
    build_topology_lock,
    resolve_topology_relation,
    validate_topology_package,
)


ROOT = Path(__file__).resolve().parent
COMMON = ROOT / "common"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _blocked(reason: str, **details: Any) -> dict[str, Any]:
    return {"status": "blocked", "reason": reason, **details}


def _require(inputs: dict[str, Any], *fields: str) -> str | None:
    for field in fields:
        if field not in inputs or inputs[field] is None:
            return field
    return None


def _topology_for(package: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    topology = _load(COMMON / "topology-package.json")
    for patch in package.get("setup", {}).get("topology_patch", []):
        if patch.get("op") != "remove_node_field":
            raise ValueError(f"Unsupported fixture topology patch: {patch}")
        for node in topology["nodes"]:
            if node.get("external_id") == patch.get("external_id"):
                node.pop(patch["field"], None)
                break
        else:
            raise ValueError(f"Fixture patch node is not present: {patch}")
    diagnostics = validate_topology_package(topology, deployment=True)
    errors = [item for item in diagnostics if item["severity"] == "error"]
    return (None, _blocked("setup_validation_error", diagnostics=errors)) if errors else (topology, None)


def _fast_breathing(inputs: dict[str, Any]) -> dict[str, Any]:
    missing = _require(inputs, "age_months", "respiratory_rate_bpm")
    if missing:
        return _blocked("missing_required_data", field=missing)
    age = inputs["age_months"]
    rate = inputs["respiratory_rate_bpm"]
    if not isinstance(age, int) or not isinstance(rate, int) or not 2 <= age < 60:
        return _blocked("manual_review_required")
    threshold = 50 if age < 12 else 40
    if rate >= threshold:
        return {"status": "classified", "classification": "SYNTHETIC_FAST", "referral": "facility_review"}
    return {"status": "classified", "classification": "SYNTHETIC_NOT_FAST"}


def _anthropometric(inputs: dict[str, Any]) -> dict[str, Any]:
    missing = _require(inputs, "age_months", "bilateral_foot_swelling")
    if missing:
        return _blocked("missing_required_data", field=missing)
    if not 6 <= inputs["age_months"] < 60:
        return _blocked("manual_review_required")
    if "muac_mm" not in inputs:
        return _blocked("missing_required_data", field="muac_mm")
    muac = inputs["muac_mm"]
    swelling = inputs["bilateral_foot_swelling"]
    if not isinstance(muac, int) or not isinstance(swelling, bool):
        return _blocked("missing_required_data")
    if swelling or muac < 115:
        return {
            "status": "classified",
            "classification": "SYNTHETIC_RED",
            "referral": "facility_review",
        }
    if muac < 125:
        return {"status": "classified", "classification": "SYNTHETIC_YELLOW", "required_capability": "nutrition-support"}
    return {"status": "classified", "classification": "SYNTHETIC_GREEN"}


def _calendar(inputs: dict[str, Any]) -> dict[str, Any]:
    missing = _require(inputs, "visit_date", "facility_time_zone")
    if missing:
        return _blocked("missing_required_data", field=missing)
    return _blocked("extension_not_available", extension="calendar-exact@1.0")


def _referral(package: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    missing = _require(inputs, "patient_id", "referral_need", "topology_snapshot_id")
    if missing:
        return _blocked("missing_required_data", field=missing)
    topology, failure = _topology_for(package)
    if failure:
        return failure
    assert topology is not None
    if inputs["topology_snapshot_id"] != topology["snapshot_id"]:
        return _blocked("topology_lock_mismatch")
    capabilities = {
        "SYNTHETIC_EMERGENCY": "emergency-care",
        "SYNTHETIC_NUTRITION": "nutrition-support",
    }
    capability = capabilities.get(inputs["referral_need"])
    if capability is None:
        return _blocked("unknown_capability")
    resolution = resolve_topology_relation(
        topology,
        {
            "relation": "referral.eligible-facilities",
            "cardinality": "collection",
            "required_capability_codes": [capability],
            "at": "2026-08-03T09:00:00Z",
            "target_backend": "cht",
        },
    )
    return {"status": resolution["status"], "relation": resolution["relation"], "matches": resolution["matches"]}


def _effect_plan(package: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    missing = _require(inputs, "patient_id", "classification", "requested_at")
    if missing:
        return _blocked("missing_required_data", field=missing)
    if inputs["classification"] != "SYNTHETIC_YELLOW":
        return {"status": "not_requested"}
    topology, failure = _topology_for(package)
    if failure:
        return failure
    assert topology is not None
    caregiver = resolve_topology_relation(
        topology,
        {
            "relation": "patient.primary-caregiver",
            "cardinality": "one",
            "subject_external_id": inputs["patient_id"],
            "at": inputs["requested_at"],
            "target_backend": "cht",
        },
    )
    if caregiver["status"] != "resolved":
        return _blocked(caregiver["status"])
    request = {
        "schema_version": "1.0",
        "source": {
            "package_id": package["fixture_id"],
            "package_version": "1.0.0",
            "trigger_id": "synthetic-yellow",
            "trigger_event_id": "synthetic-encounter",
            "provenance": [{"quotation": "create a follow-up plan", "page": 1}],
        },
        "capability": "external-effect.send-approved-message@1.0.0",
        "subject": "current_patient",
        "recipient_relation": "patient.primary-caregiver",
        "purpose": "synthetic_follow_up",
        "channel": "sms",
        "urgency": "routine",
        "template": {
            "id": "synthetic-follow-up",
            "version": "1.0.0",
            "locale": "en",
            "variables": {"child_label": "synthetic child"},
        },
        "adapter": {"id": "synthetic-sms", "version": "1.0.0"},
        "requested_at": inputs["requested_at"],
        "policy": {"id": "synthetic-caregiver-policy", "version": "1.0.0"},
        "topology_snapshot_id": topology["snapshot_id"],
        "acknowledgment": {"required": False},
    }
    planned = build_external_effect_package(
        [request],
        _load(COMMON / "external-effect-catalog.json"),
        resolved_capabilities={"external-effect.send-approved-message@1.0.0"},
        topology_lock=build_topology_lock(topology),
        clinical_logic_content_sha256="a" * 64,
    )
    return {
        "status": "planned",
        "recipient_relation": caregiver["relation"],
        "request_state": planned["external_effect_requests"][0]["state"],
        "runtime_status": planned["runtime_status"],
    }


def _priority(inputs: dict[str, Any]) -> dict[str, Any]:
    missing = _require(inputs, "danger_a", "danger_b", "routine_condition")
    if missing:
        return _blocked("missing_required_data", field=missing)
    if inputs["danger_a"] or inputs["danger_b"]:
        return {"status": "classified", "classification": "SYNTHETIC_PRIORITY_EXIT"}
    if inputs["routine_condition"]:
        return {"status": "classified", "classification": "SYNTHETIC_ROUTINE"}
    return {"status": "classified", "classification": "SYNTHETIC_NO_ACTION"}


def evaluate_fixture_case(package: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a raw fixture patient with the independent test oracle."""
    fixture_id = package["fixture_id"]
    if package["fixture_status"] == "source_blocked":
        if fixture_id == "underspecified-responsibility" and not inputs.get("synthetic_flag"):
            return {"status": "not_requested"}
        if fixture_id == "conflicting-disposition" and not inputs.get("synthetic_marker_x"):
            return {"status": "not_requested"}
        return _blocked(package["source_oracle"]["required_finding"])
    if fixture_id == "fast-breathing-age-bands":
        return _fast_breathing(inputs)
    if fixture_id == "anthropometric-boundaries":
        return _anthropometric(inputs)
    if fixture_id == "exact-calendar-extension":
        return _calendar(inputs)
    if fixture_id == "referral-capability-topology":
        return _referral(package, inputs)
    if fixture_id == "follow-up-effect-planning":
        return _effect_plan(package, inputs)
    if fixture_id == "priority-and-missingness":
        return _priority(inputs)
    if fixture_id == "missing-chw-identity":
        _, failure = _topology_for(package)
        return {
            **(failure or _blocked("setup_validation_error")),
            "before": "clinical_execution",
        }
    raise ValueError(f"No reference oracle is registered for {fixture_id}")
