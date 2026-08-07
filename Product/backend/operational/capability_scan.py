"""Strict Prompt B construction, invocation, parsing, and evaluation.

This module deliberately has no registry input. Prompt B identifies local,
source-grounded needs; later deterministic work may resolve reviewed needs.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .capability_scan_prompt import CAPABILITY_SCAN_PROMPT


SCHEMA_VERSION = "capability-needs@1.0.0"
_SCHEMA_PATH = Path(__file__).with_name("schemas") / "capability-needs.schema.json"
_ROOT_FIELDS = {"schema_version", "candidates"}
_CANDIDATE_FIELDS = {
    "local_id", "need_kind", "problem", "inputs", "outputs",
    "required_statuses", "failure_behavior", "subject_scope", "uncertainty",
    "source", "provenance",
}
_PARAMETER_FIELDS = {"name", "data_type", "unit"}
_SOURCE_FIELDS = {"document_id", "page", "section", "quote"}
_UNCERTAINTY_FIELDS = {"status", "details"}
_PROVENANCE_FIELDS = {"origin", "source_digest"}
_DATA_TYPES = {"boolean", "code", "date", "datetime", "decimal", "integer", "reference", "string"}
_NEED_KINDS = {"technical_calculation", "local_data_read"}
_STATUSES = {
    "success", "missing_input", "invalid_input", "out_of_range",
    "missing_reference_data", "version_mismatch", "ambiguous_input", "unsupported_scope", "error",
}
_FAILURE_BEHAVIORS = {"return_status", "block", "flag_for_review"}
_SUBJECT_SCOPES = {"current_contact", "individual", "household", "group", "facility", "unknown"}
_UNCERTAINTY = {"none", "ambiguous", "insufficient_grounding", "unit_mismatch", "unsupported_scope"}
_LOCAL_ID = re.compile(r"^need_[a-z0-9_]+$")
_PARAMETER_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_UNIT = re.compile(r"^[A-Za-z0-9%._/-]{1,40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CapabilityScanValidationError(ValueError):
    """Raised when Prompt B input or output violates its strict contract."""


def load_candidate_needs_schema() -> dict[str, Any]:
    """Return an isolated copy of the published Prompt B output schema."""
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CapabilityScanValidationError(f"{label} must be an object")
    return value


def _exact_fields(value: dict[str, Any], expected: set[str], label: str) -> None:
    missing = expected - value.keys()
    extra = value.keys() - expected
    if missing:
        raise CapabilityScanValidationError(f"{label} missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise CapabilityScanValidationError(f"{label} has unknown fields: {', '.join(sorted(extra))}")


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CapabilityScanValidationError(f"{label} must be a non-empty string")
    return value


def normalize_manual(manual: dict[str, Any]) -> dict[str, Any]:
    """Validate a supplied manual without accepting any answer annotations."""
    manual = _mapping(manual, "manual")
    _exact_fields(manual, {"document_id", "sections"}, "manual")
    document_id = _string(manual["document_id"], "manual.document_id")
    if not isinstance(manual["sections"], list) or not manual["sections"]:
        raise CapabilityScanValidationError("manual.sections must be a non-empty array")
    sections: list[dict[str, str]] = []
    for index, raw in enumerate(manual["sections"]):
        section = _mapping(raw, f"manual.sections[{index}]")
        _exact_fields(section, {"page", "section", "text"}, f"manual.sections[{index}]")
        sections.append({
            "page": _string(section["page"], f"manual.sections[{index}].page"),
            "section": _string(section["section"], f"manual.sections[{index}].section"),
            "text": _string(section["text"], f"manual.sections[{index}].text"),
        })
    return {"document_id": document_id, "sections": sections}


def manual_digest(manual: dict[str, Any]) -> str:
    normalized = normalize_manual(manual)
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_capability_scan_request(manual: dict[str, Any]) -> dict[str, Any]:
    """Build the complete registry-blind Prompt B request."""
    normalized = normalize_manual(manual)
    return {
        "system_instructions": CAPABILITY_SCAN_PROMPT,
        "output_schema": load_candidate_needs_schema(),
        "source_digest": manual_digest(normalized),
        "manual": deepcopy(normalized),
    }


def _validate_parameter(raw: Any, label: str) -> dict[str, Any]:
    value = _mapping(raw, label)
    _exact_fields(value, _PARAMETER_FIELDS, label)
    name = _string(value["name"], f"{label}.name")
    if not _PARAMETER_NAME.fullmatch(name):
        raise CapabilityScanValidationError(f"{label}.name is not a local parameter name")
    if value["data_type"] not in _DATA_TYPES:
        raise CapabilityScanValidationError(f"{label}.data_type is unsupported")
    unit = value["unit"]
    if unit is not None and (not isinstance(unit, str) or not _UNIT.fullmatch(unit)):
        raise CapabilityScanValidationError(f"{label}.unit is malformed")
    return deepcopy(value)


def parse_candidate_needs(raw: str | dict[str, Any], manual: dict[str, Any]) -> dict[str, Any]:
    """Strictly validate output and prove every quote against its location."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CapabilityScanValidationError("Prompt B output must be JSON") from exc
    root = _mapping(raw, "candidate needs")
    _exact_fields(root, _ROOT_FIELDS, "candidate needs")
    if root["schema_version"] != SCHEMA_VERSION:
        raise CapabilityScanValidationError(f"schema_version must be {SCHEMA_VERSION}")
    if not isinstance(root["candidates"], list):
        raise CapabilityScanValidationError("candidates must be an array")

    normalized_manual = normalize_manual(manual)
    digest = manual_digest(normalized_manual)
    locations = {
        (normalized_manual["document_id"], section["page"], section["section"]): section["text"]
        for section in normalized_manual["sections"]
    }
    parsed: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_candidate in enumerate(root["candidates"]):
        label = f"candidates[{index}]"
        candidate = _mapping(raw_candidate, label)
        _exact_fields(candidate, _CANDIDATE_FIELDS, label)
        local_id = _string(candidate["local_id"], f"{label}.local_id")
        if not _LOCAL_ID.fullmatch(local_id):
            raise CapabilityScanValidationError(f"{label}.local_id must be a local need_ identifier")
        if local_id in seen_ids:
            raise CapabilityScanValidationError(f"duplicate local candidate ID: {local_id}")
        seen_ids.add(local_id)
        if candidate["need_kind"] not in _NEED_KINDS:
            raise CapabilityScanValidationError(f"{label}.need_kind is unsupported")
        _string(candidate["problem"], f"{label}.problem")

        for field in ("inputs", "outputs"):
            if not isinstance(candidate[field], list):
                raise CapabilityScanValidationError(f"{label}.{field} must be an array")
            if field == "outputs" and not candidate[field]:
                raise CapabilityScanValidationError(f"{label}.outputs must not be empty")
            candidate[field] = [
                _validate_parameter(item, f"{label}.{field}[{position}]")
                for position, item in enumerate(candidate[field])
            ]

        statuses = candidate["required_statuses"]
        if not isinstance(statuses, list) or not statuses or len(statuses) != len(set(statuses)):
            raise CapabilityScanValidationError(f"{label}.required_statuses must be a non-empty unique array")
        if any(status not in _STATUSES for status in statuses):
            raise CapabilityScanValidationError(f"{label}.required_statuses contains an unsupported status")
        if candidate["failure_behavior"] not in _FAILURE_BEHAVIORS:
            raise CapabilityScanValidationError(f"{label}.failure_behavior is unsupported")
        if candidate["subject_scope"] not in _SUBJECT_SCOPES:
            raise CapabilityScanValidationError(f"{label}.subject_scope is unsupported")

        uncertainty = _mapping(candidate["uncertainty"], f"{label}.uncertainty")
        _exact_fields(uncertainty, _UNCERTAINTY_FIELDS, f"{label}.uncertainty")
        if uncertainty["status"] not in _UNCERTAINTY:
            raise CapabilityScanValidationError(f"{label}.uncertainty.status is unsupported")
        if uncertainty["details"] is not None:
            _string(uncertainty["details"], f"{label}.uncertainty.details")
        if uncertainty["status"] == "none":
            if uncertainty["details"] is not None:
                raise CapabilityScanValidationError(
                    f"{label}.uncertainty.details must be null when status is none"
                )
            if "success" not in statuses:
                raise CapabilityScanValidationError(
                    f"{label}.required_statuses must include success when uncertainty is none"
                )
        else:
            if uncertainty["details"] is None:
                raise CapabilityScanValidationError(
                    f"{label}.uncertainty.details must explain non-none uncertainty"
                )
            if "success" in statuses or candidate["failure_behavior"] == "return_status":
                raise CapabilityScanValidationError(
                    f"{label} must fail closed while uncertainty is unresolved"
                )

        source = _mapping(candidate["source"], f"{label}.source")
        _exact_fields(source, _SOURCE_FIELDS, f"{label}.source")
        key = tuple(_string(source[field], f"{label}.source.{field}") for field in ("document_id", "page", "section"))
        quote = _string(source["quote"], f"{label}.source.quote")
        if key not in locations:
            raise CapabilityScanValidationError(f"{label}.source location is not in the supplied manual")
        if quote not in locations[key]:
            raise CapabilityScanValidationError(f"{label}.source.quote is not an exact substring at its location")

        provenance = _mapping(candidate["provenance"], f"{label}.provenance")
        _exact_fields(provenance, _PROVENANCE_FIELDS, f"{label}.provenance")
        if provenance["origin"] != "manual":
            raise CapabilityScanValidationError(f"{label}.provenance.origin must be manual")
        if not isinstance(provenance["source_digest"], str) or not _SHA256.fullmatch(provenance["source_digest"]):
            raise CapabilityScanValidationError(f"{label}.provenance.source_digest must be SHA-256")
        if provenance["source_digest"] != digest:
            raise CapabilityScanValidationError(f"{label}.provenance.source_digest does not match the supplied manual")
        parsed.append(deepcopy(candidate))
    return {"schema_version": SCHEMA_VERSION, "candidates": parsed}


def scan_capability_needs(
    manual: dict[str, Any],
    invoke_model: Callable[[dict[str, Any]], str | dict[str, Any]],
) -> dict[str, Any]:
    """Invoke an explicitly supplied model adapter and parse its output."""
    if not callable(invoke_model):
        raise TypeError("invoke_model must be callable")
    request = build_capability_scan_request(manual)
    return parse_candidate_needs(invoke_model(request), manual)


def _metric(score: float, threshold: float) -> dict[str, Any]:
    rounded = round(score, 4)
    return {"score": rounded, "threshold": threshold, "status": "pass" if score >= threshold else "fail"}


def evaluate_candidate_needs(
    manual: dict[str, Any], raw: str | dict[str, Any], expected: list[dict[str, str]]
) -> dict[str, Any]:
    """Score one output without exposing ``expected`` to prompt construction."""
    try:
        parsed = parse_candidate_needs(raw, manual)
    except CapabilityScanValidationError as exc:
        return {
            "status": "fail",
            "error": str(exc),
            "metrics": {name: _metric(0.0, threshold) for name, threshold in {
                "precision": 1.0, "recall": 1.0, "grounding": 1.0,
                "unsupported_inference": 1.0, "ambiguity": 1.0,
            }.items()},
        }
    predicted = {
        (item["need_kind"], item["source"]["quote"], item["uncertainty"]["status"])
        for item in parsed["candidates"]
    }
    expected_set = {
        (item["need_kind"], item["source_quote"], item["uncertainty_status"])
        for item in expected
    }
    matches = predicted & expected_set
    precision = len(matches) / len(predicted) if predicted else (1.0 if not expected_set else 0.0)
    recall = len(matches) / len(expected_set) if expected_set else (1.0 if not predicted else 0.0)
    unsupported = 1.0 - (len(predicted - expected_set) / len(predicted)) if predicted else 1.0
    expected_ambiguous = {item for item in expected_set if item[2] != "none"}
    predicted_ambiguous = {item for item in predicted if item[2] != "none"}
    ambiguity = (
        len(expected_ambiguous & predicted_ambiguous) / len(expected_ambiguous)
        if expected_ambiguous else (1.0 if not predicted_ambiguous else 0.0)
    )
    metrics = {
        "precision": _metric(precision, 1.0),
        "recall": _metric(recall, 1.0),
        "grounding": _metric(1.0, 1.0),
        "unsupported_inference": _metric(unsupported, 1.0),
        "ambiguity": _metric(ambiguity, 1.0),
    }
    status = "pass" if all(item["status"] == "pass" for item in metrics.values()) else "fail"
    return {"status": status, "metrics": metrics}
