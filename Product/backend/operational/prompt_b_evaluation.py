"""Recorded and opt-in live evaluation support for Prompt B."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from .capability_scan import (
    build_capability_scan_request,
    evaluate_candidate_needs,
    manual_digest,
    scan_capability_needs,
)


NOT_RUN_METRIC = {"score": None, "threshold": 1.0, "status": "not_run"}


def load_evaluation_cases(path: Path) -> list[dict[str, Any]]:
    """Load sealed cases and materialize their source-digest placeholders."""
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("Prompt B evaluation cases must be a non-empty array")
    materialized = deepcopy(cases)
    for case in materialized:
        digest = manual_digest(case["manual"])
        for candidate in case["recorded_output"]["candidates"]:
            if candidate["provenance"].get("source_digest") != "$SOURCE_DIGEST":
                raise ValueError(f"{case.get('id', '<unknown>')} has an unsealed source digest")
            candidate["provenance"]["source_digest"] = digest
    return materialized


def run_prompt_b_evaluation(
    cases: list[dict[str, Any]],
    invoke_model: Callable[[dict[str, Any]], str | dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run live evaluation, or explicitly report that it was not run."""
    if invoke_model is None:
        return {
            "evidence_level": "E0",
            "status": "not_run",
            "reason": "no live-model adapter supplied",
            "cases": [
                {
                    "id": case["id"],
                    "status": "not_run",
                    "metrics": {
                        name: dict(NOT_RUN_METRIC)
                        for name in ("precision", "recall", "grounding", "unsupported_inference", "ambiguity")
                    },
                }
                for case in cases
            ],
        }

    results: list[dict[str, Any]] = []
    for case in cases:
        request = build_capability_scan_request(case["manual"])
        raw = invoke_model(request)
        result = evaluate_candidate_needs(case["manual"], raw, case["expected"])
        results.append({"id": case["id"], **result})
    return {
        "evidence_level": "E2",
        "status": "pass" if all(item["status"] == "pass" for item in results) else "fail",
        "cases": results,
    }


def recorded_evaluation(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate committed outputs without calling a model."""
    results = [
        {
            "id": case["id"],
            **evaluate_candidate_needs(case["manual"], case["recorded_output"], case["expected"]),
        }
        for case in cases
    ]
    return {
        "evidence_level": "E2",
        "status": "pass" if all(item["status"] == "pass" for item in results) else "fail",
        "cases": results,
    }


def invoke_case(
    case: dict[str, Any], invoke_model: Callable[[dict[str, Any]], str | dict[str, Any]]
) -> dict[str, Any]:
    """Direct, importable invocation path used by adapters and tests."""
    return scan_capability_needs(case["manual"], invoke_model)
