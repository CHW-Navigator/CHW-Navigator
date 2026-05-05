from __future__ import annotations

import json
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .clinical_ir import ClinicalIRDocument, ScalarType
from .dmn import import_dmn_decisions
from .evaluator import evaluate_document
from .form_ir import XLSFormWorkbook
from .mermaid_backend import build_mermaid_artifact
from .xlsform_backend import build_xlsform
from .xlsform_runtime import evaluate_workbook
from .z3_backend import (
    Z3AnalysisReport,
    Z3CheckResult,
    Z3GeneratedCase,
    Z3Witness,
    analyze_document,
    evaluate_patient,
    generate_test_patients,
)


class ComparisonError(Exception):
    """Raised when backend comparison cannot be performed for the requested cases."""


@dataclass(slots=True)
class ComparisonCase:
    name: str
    values: dict[str, Any]
    missing: set[str] = field(default_factory=set)
    category: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MismatchEntry:
    field: str
    category: str
    expected_engine: str
    actual_engine: str
    expected_value: Any
    actual_value: Any


@dataclass(slots=True)
class CaseResult:
    name: str
    ok: bool
    inputs: dict[str, Any]
    missing: list[str] = field(default_factory=list)
    category: str | None = None
    tags: list[str] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)
    mismatch_entries: list[MismatchEntry] = field(default_factory=list)
    interpreter_predicates: dict[str, Any] = field(default_factory=dict)
    interpreter_outputs: dict[str, Any] = field(default_factory=dict)
    interpreter_rule_hits: dict[str, bool] = field(default_factory=dict)
    dmn_predicates: dict[str, Any] = field(default_factory=dict)
    dmn_outputs: dict[str, Any] = field(default_factory=dict)
    dmn_rule_hits: dict[str, bool] = field(default_factory=dict)
    xlsform_predicates: dict[str, Any] = field(default_factory=dict)
    xlsform_outputs: dict[str, Any] = field(default_factory=dict)
    xlsform_rule_hits: dict[str, Any] = field(default_factory=dict)
    z3_predicates: dict[str, Any] | None = None
    z3_outputs: dict[str, Any] | None = None
    z3_rule_hits: dict[str, Any] | None = None
    mermaid_ok: bool = True
    mermaid_trace_nodes: list[str] = field(default_factory=list)
    mermaid_missing_nodes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PairwiseCaseResult:
    name: str
    ok: bool
    inputs: dict[str, Any]
    missing: list[str] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)
    mismatch_entries: list[MismatchEntry] = field(default_factory=list)
    expected_predicates: dict[str, Any] = field(default_factory=dict)
    expected_outputs: dict[str, Any] = field(default_factory=dict)
    expected_rule_hits: dict[str, bool] = field(default_factory=dict)
    actual_predicates: dict[str, Any] = field(default_factory=dict)
    actual_outputs: dict[str, Any] = field(default_factory=dict)
    actual_rule_hits: dict[str, Any] = field(default_factory=dict)


def compare_backends(
    document: ClinicalIRDocument,
    dmn_path: str | None = None,
    patient_cases: list[ComparisonCase] | None = None,
) -> list[CaseResult]:
    built = build_xlsform(document)
    mermaid = build_mermaid_artifact(document)
    dmn_document = import_dmn_decisions(document, dmn_path) if dmn_path else None
    cases = patient_cases or _derive_comparison_cases(document)

    if not cases:
        raise ComparisonError("no comparison cases are available")

    results: list[CaseResult] = []
    for case in cases:
        _validate_compare_case(document, case)

        interpreter = evaluate_document(document, case.values, case.missing)
        dmn_eval = evaluate_document(dmn_document, case.values, case.missing) if dmn_document else None
        z3_eval = evaluate_patient(document, case.values, case.missing)
        xlsform_eval = evaluate_workbook(
            built.workbook,
            _coerce_patient_values(document, case.values, case.missing),
        )

        interpreter_rule_hits = _decision_traces_to_rule_hits(document, interpreter.decisions)
        dmn_rule_hits = _decision_traces_to_rule_hits(dmn_document, dmn_eval.decisions) if dmn_eval and dmn_document else {}
        xlsform_predicates = {
            predicate_id: xlsform_eval.values.get(predicate_id)
            for predicate_id in document.predicates
        }
        xlsform_outputs = {
            output_id: xlsform_eval.values.get(output_id)
            for output_id in document.outputs
        }
        xlsform_rule_hits = {
            rule_id: xlsform_eval.values.get(row_name)
            for rule_id, row_name in built.rule_row_names.items()
        }
        mermaid_trace_nodes, mermaid_missing_nodes = _mermaid_trace(interpreter_rule_hits, interpreter.outputs, document, mermaid)
        mismatch_entries: list[MismatchEntry] = []

        if dmn_eval is not None:
            mismatch_entries.extend(_compare_dicts("predicate", "interpreter", "dmn", interpreter.predicates, dmn_eval.predicates))
            mismatch_entries.extend(_compare_dicts("output", "interpreter", "dmn", interpreter.outputs, dmn_eval.outputs))
            mismatch_entries.extend(_compare_dicts("rule_hit", "interpreter", "dmn", interpreter_rule_hits, dmn_rule_hits))

        mismatch_entries.extend(_compare_dicts("predicate", "interpreter", "xlsform", interpreter.predicates, xlsform_predicates))
        mismatch_entries.extend(_compare_dicts("output", "interpreter", "xlsform", interpreter.outputs, xlsform_outputs))
        mismatch_entries.extend(_compare_dicts("rule_hit", "interpreter", "xlsform", interpreter_rule_hits, xlsform_rule_hits))
        mismatch_entries.extend(_compare_dicts("predicate", "interpreter", "z3", interpreter.predicates, z3_eval.predicates))
        mismatch_entries.extend(_compare_dicts("output", "interpreter", "z3", interpreter.outputs, z3_eval.outputs))
        mismatch_entries.extend(_compare_dicts("rule_hit", "interpreter", "z3", interpreter_rule_hits, z3_eval.rule_hits))
        if mermaid_missing_nodes:
            mismatch_entries.extend(
                MismatchEntry(
                    field=node_id,
                    category="mermaid_node",
                    expected_engine="interpreter",
                    actual_engine="mermaid",
                    expected_value=True,
                    actual_value=False,
                )
                for node_id in mermaid_missing_nodes
            )
        mismatch_messages = [_render_mismatch_message(item) for item in mismatch_entries]

        results.append(
            CaseResult(
                name=case.name,
                ok=not mismatch_entries,
                inputs=case.values,
                missing=sorted(case.missing),
                category=case.category,
                tags=list(case.tags),
                mismatches=mismatch_messages,
                mismatch_entries=mismatch_entries,
                interpreter_predicates=interpreter.predicates,
                interpreter_outputs=interpreter.outputs,
                interpreter_rule_hits=interpreter_rule_hits,
                dmn_predicates=dmn_eval.predicates if dmn_eval else {},
                dmn_outputs=dmn_eval.outputs if dmn_eval else {},
                dmn_rule_hits=dmn_rule_hits,
                xlsform_predicates=xlsform_predicates,
                xlsform_outputs=xlsform_outputs,
                xlsform_rule_hits=xlsform_rule_hits,
                z3_predicates=z3_eval.predicates,
                z3_outputs=z3_eval.outputs,
                z3_rule_hits=z3_eval.rule_hits,
                mermaid_ok=not mermaid_missing_nodes,
                mermaid_trace_nodes=mermaid_trace_nodes,
                mermaid_missing_nodes=mermaid_missing_nodes,
            )
        )

    return results


def load_patient_cases(path: str) -> list[ComparisonCase]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ComparisonError(f"patient case file '{path}' not found") from exc
    except OSError as exc:
        raise ComparisonError(f"could not read patient case file '{path}': {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ComparisonError(
            f"patient case file '{path}' is not valid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}"
        ) from exc
    raw_cases = data.get("cases", data) if isinstance(data, dict) else data
    if not isinstance(raw_cases, list):
        raise ComparisonError("patient case file must be a list or an object with a 'cases' list")

    cases: list[ComparisonCase] = []
    for index, item in enumerate(raw_cases):
        if not isinstance(item, dict):
            raise ComparisonError(f"patient case at index {index} must be an object")
        values = item.get("values", {})
        raw_missing = item.get("missing", [])
        if not isinstance(values, dict):
            raise ComparisonError(f"patient case at index {index} must include an object-valued 'values' field")
        if not isinstance(raw_missing, list) or not all(isinstance(entry, str) for entry in raw_missing):
            raise ComparisonError(f"patient case at index {index} must include a string-valued 'missing' list")
        missing = set(raw_missing)
        name = str(item.get("name", f"case_{index + 1}"))
        raw_tags = item.get("tags", [])
        if not isinstance(raw_tags, list) or not all(isinstance(entry, str) for entry in raw_tags):
            raise ComparisonError(f"patient case at index {index} must include a string-valued 'tags' list when present")
        raw_category = item.get("category")
        if raw_category is not None and not isinstance(raw_category, str):
            raise ComparisonError(f"patient case at index {index} must include a string-valued 'category' field when present")
        cases.append(
            ComparisonCase(
                name=name,
                values=dict(values),
                missing=missing,
                category=raw_category,
                tags=list(raw_tags),
            )
        )
    return cases


def compare_document_pair(
    expected_document: ClinicalIRDocument,
    actual_document: ClinicalIRDocument,
    patient_cases: list[ComparisonCase],
    *,
    label: str = "candidate",
) -> list[PairwiseCaseResult]:
    results: list[PairwiseCaseResult] = []
    for case in patient_cases:
        _validate_compare_case(expected_document, case)

        expected_eval = evaluate_document(expected_document, case.values, case.missing)
        actual_eval = evaluate_document(actual_document, case.values, case.missing)
        expected_rule_hits = _decision_traces_to_rule_hits(expected_document, expected_eval.decisions)
        actual_rule_hits = _decision_traces_to_rule_hits(actual_document, actual_eval.decisions)

        mismatch_entries: list[MismatchEntry] = []
        mismatch_entries.extend(_compare_dicts("predicate", "expected", label, expected_eval.predicates, actual_eval.predicates))
        mismatch_entries.extend(_compare_dicts("output", "expected", label, expected_eval.outputs, actual_eval.outputs))
        mismatch_entries.extend(_compare_dicts("rule_hit", "expected", label, expected_rule_hits, actual_rule_hits))
        mismatch_messages = [_render_mismatch_message(item) for item in mismatch_entries]

        results.append(
            PairwiseCaseResult(
                name=case.name,
                ok=not mismatch_entries,
                inputs=case.values,
                missing=sorted(case.missing),
                mismatches=mismatch_messages,
                mismatch_entries=mismatch_entries,
                expected_predicates=expected_eval.predicates,
                expected_outputs=expected_eval.outputs,
                expected_rule_hits=expected_rule_hits,
                actual_predicates=actual_eval.predicates,
                actual_outputs=actual_eval.outputs,
                actual_rule_hits=actual_rule_hits,
            )
        )
    return results


def compare_workbook_pair(
    expected_document: ClinicalIRDocument,
    workbook: XLSFormWorkbook,
    patient_cases: list[ComparisonCase],
    *,
    label: str = "workbook",
) -> list[PairwiseCaseResult]:
    results: list[PairwiseCaseResult] = []
    for case in patient_cases:
        _validate_compare_case(expected_document, case)

        expected_eval = evaluate_document(expected_document, case.values, case.missing)
        workbook_eval = evaluate_workbook(
            workbook,
            _coerce_patient_values(expected_document, case.values, case.missing),
        )
        expected_rule_hits = _decision_traces_to_rule_hits(expected_document, expected_eval.decisions)
        workbook_predicates = {
            predicate_id: workbook_eval.values.get(predicate_id)
            for predicate_id in expected_document.predicates
        }
        workbook_outputs = {
            output_id: workbook_eval.values.get(output_id)
            for output_id in expected_document.outputs
        }
        workbook_rule_hits = {
            rule.id: workbook_eval.values.get(f"rh_{rule.id}")
            for decision in expected_document.decisions.values()
            for rule in decision.rules
        }

        mismatch_entries: list[MismatchEntry] = []
        mismatch_entries.extend(_compare_dicts("predicate", "expected", label, expected_eval.predicates, workbook_predicates))
        mismatch_entries.extend(_compare_dicts("output", "expected", label, expected_eval.outputs, workbook_outputs))
        mismatch_entries.extend(_compare_dicts("rule_hit", "expected", label, expected_rule_hits, workbook_rule_hits))
        mismatch_messages = [_render_mismatch_message(item) for item in mismatch_entries]

        results.append(
            PairwiseCaseResult(
                name=case.name,
                ok=not mismatch_entries,
                inputs=case.values,
                missing=sorted(case.missing),
                mismatches=mismatch_messages,
                mismatch_entries=mismatch_entries,
                expected_predicates=expected_eval.predicates,
                expected_outputs=expected_eval.outputs,
                expected_rule_hits=expected_rule_hits,
                actual_predicates=workbook_predicates,
                actual_outputs=workbook_outputs,
                actual_rule_hits=workbook_rule_hits,
            )
        )
    return results


def _derive_comparison_cases(document: ClinicalIRDocument) -> list[ComparisonCase]:
    generated_cases = generate_test_patients(document)
    return [_comparison_case_from_generated(item) for item in generated_cases]


def _coerce_patient_values(
    document: ClinicalIRDocument,
    inputs: dict[str, Any],
    missing: set[str] | None = None,
) -> dict[str, Any]:
    missing_inputs = missing or set()
    for key in missing_inputs:
        if key in inputs and inputs[key] is not None:
            raise ComparisonError(
                f"comparison input '{key}' is marked missing but also has a concrete value; use one representation"
            )
    coerced = {key: value for key, value in inputs.items() if key not in missing_inputs}
    for key, value in list(coerced.items()):
        variable = document.variables.get(key)
        if value is None:
            raise ComparisonError(
                f"comparison input '{key}' has value None; mark it missing explicitly instead of coercing it"
            )
        if variable is not None and variable.type is ScalarType.BOOL:
            if not isinstance(value, bool):
                raise ComparisonError(
                    f"comparison input '{key}' must be a Boolean when present; got {type(value).__name__}"
                )
            coerced[key] = "true" if value else "false"
    return coerced


def _validate_compare_case(document: ClinicalIRDocument, case: ComparisonCase) -> None:
    overlap = case.missing & set(case.values)
    if overlap:
        raise ComparisonError(
            f"comparison case '{case.name}' marks inputs as missing and present at the same time: {sorted(overlap)}"
        )
    for key, value in case.values.items():
        if value is None:
            raise ComparisonError(
                f"comparison case '{case.name}' provides None for '{key}'; mark it missing explicitly instead"
            )
        variable = document.variables.get(key)
        if variable is not None and variable.type is ScalarType.BOOL and not isinstance(value, bool):
            raise ComparisonError(
                f"comparison case '{case.name}' must provide a Boolean for '{key}' when present; got {type(value).__name__}"
            )


def build_comparison_log(
    *,
    guideline_id: str,
    results: list[CaseResult],
    generated_at: str | None = None,
    compiler_version: str | None = None,
    source_artifacts: dict[str, Any] | None = None,
    provenance: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "log_type": "comparison_report",
        "contract_version": 1,
        "guideline_id": guideline_id,
        "generated_at": generated_at or _timestamp_utc(),
        "compiler_version": compiler_version,
        "source_artifacts": source_artifacts or {},
        "provenance": provenance or [],
        "results": [_render_case_result(item) for item in results],
    }


def build_z3_checks_log(
    *,
    guideline_id: str,
    report: Z3AnalysisReport,
    generated_at: str | None = None,
    compiler_version: str | None = None,
    source_artifacts: dict[str, Any] | None = None,
    provenance: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ordered_results = (
        report.predicate_satisfiability
        + report.predicate_missingness
        + report.rule_reachability
        + report.output_reachability
        + report.decision_overlaps
        + report.fallback_reachability
        + report.invariant_violations
    )
    return {
        "log_type": "z3_checks",
        "contract_version": 1,
        "guideline_id": guideline_id,
        "generated_at": generated_at or _timestamp_utc(),
        "compiler_version": compiler_version,
        "source_artifacts": source_artifacts or {},
        "provenance": provenance or [],
        "results": [_render_z3_check(item) for item in ordered_results],
    }


def _compare_dicts(
    category: str,
    expected_engine: str,
    actual_engine: str,
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> list[MismatchEntry]:
    mismatches: list[MismatchEntry] = []
    keys = sorted(set(expected) | set(actual))
    for key in keys:
        expected_value = expected.get(key)
        actual_value = actual.get(key)
        if actual_value != expected_value:
            mismatches.append(
                MismatchEntry(
                    field=key,
                    category=category,
                    expected_engine=expected_engine,
                    actual_engine=actual_engine,
                    expected_value=expected_value,
                    actual_value=actual_value,
                )
            )
    return mismatches


def _comparison_case_from_generated(case: Z3GeneratedCase) -> ComparisonCase:
    return ComparisonCase(
        name=case.name,
        values=dict(case.values),
        missing=set(case.missing),
        category=case.category,
        tags=list(case.tags),
    )


def _case_key(inputs: dict[str, Any]) -> str:
    return "|".join(f"{key}={inputs[key]!r}" for key in sorted(inputs))


def _decision_traces_to_rule_hits(document: ClinicalIRDocument, decisions) -> dict[str, bool]:
    result: dict[str, bool] = {
        rule.id: False
        for decision in document.decisions.values()
        for rule in decision.rules
    }
    for trace in decisions:
        if trace.fired_rule_id is not None:
            result[trace.fired_rule_id] = True
    return result


def _sanitize_case_name(name: str) -> str:
    return name.replace(":", "_").replace(",", "_")


def _mermaid_trace(
    interpreter_rule_hits: dict[str, bool],
    outputs: dict[str, Any],
    document: ClinicalIRDocument,
    mermaid,
) -> tuple[list[str], list[str]]:
    trace_nodes: list[str] = []
    missing_nodes: list[str] = []

    decision_lookup = {
        rule.id: decision.id
        for decision in document.decisions.values()
        for rule in decision.rules
    }
    for rule_id, hit in interpreter_rule_hits.items():
        if not hit:
            continue
        decision_id = decision_lookup[rule_id]
        trace_nodes.append(decision_id)
        trace_nodes.append(f"{decision_id}__{rule_id}")

    for output_id, value in outputs.items():
        if value not in {False, None, ""}:
            trace_nodes.append(output_id)

    unique_trace_nodes: list[str] = []
    for node_id in trace_nodes:
        if node_id not in unique_trace_nodes:
            unique_trace_nodes.append(node_id)
        if node_id not in mermaid.node_sources:
            missing_nodes.append(node_id)
    return unique_trace_nodes, missing_nodes


def _render_mismatch_message(entry: MismatchEntry) -> str:
    engine_label = {
        "dmn": "DMN",
        "xlsform": "XLSForm",
        "z3": "Z3",
        "mermaid": "Mermaid",
    }.get(entry.actual_engine, entry.actual_engine)
    return (
        f"{engine_label} {entry.category}s mismatch for '{entry.field}': "
        f"expected {entry.expected_value!r}, got {entry.actual_value!r}"
    )


def _render_case_result(result: CaseResult) -> dict[str, Any]:
    return {
        "name": result.name,
        "ok": result.ok,
        "category": result.category,
        "tags": result.tags,
        "inputs": result.inputs,
        "missing": result.missing,
        "interpreter_predicates": result.interpreter_predicates,
        "interpreter_outputs": result.interpreter_outputs,
        "interpreter_rule_hits": result.interpreter_rule_hits,
        "dmn_predicates": result.dmn_predicates,
        "dmn_outputs": result.dmn_outputs,
        "dmn_rule_hits": result.dmn_rule_hits,
        "xlsform_predicates": result.xlsform_predicates,
        "xlsform_outputs": result.xlsform_outputs,
        "xlsform_rule_hits": result.xlsform_rule_hits,
        "z3_predicates": result.z3_predicates,
        "z3_outputs": result.z3_outputs,
        "z3_rule_hits": result.z3_rule_hits,
        "mermaid_ok": result.mermaid_ok,
        "mermaid_trace_nodes": result.mermaid_trace_nodes,
        "mermaid_missing_nodes": result.mermaid_missing_nodes,
        "mismatches": [_render_mismatch_entry(item) for item in result.mismatch_entries],
    }


def _render_mismatch_entry(entry: MismatchEntry) -> dict[str, Any]:
    return {
        "field": entry.field,
        "category": entry.category,
        "expected_engine": entry.expected_engine,
        "actual_engine": entry.actual_engine,
        "expected_value": entry.expected_value,
        "actual_value": entry.actual_value,
    }


def _render_z3_check(result: Z3CheckResult) -> dict[str, Any]:
    rendered = {
        "category": result.category,
        "target": result.target,
        "ok": result.ok,
        "message": result.message,
    }
    if result.witness is not None:
        rendered["witness"] = _render_z3_witness(result.witness)
    return rendered


def _render_z3_witness(witness: Z3Witness) -> dict[str, Any]:
    return {
        "values": {key: value for key, value in witness.inputs.items() if not witness.input_missing.get(key, False)},
        "missing": sorted(key for key, missing in witness.input_missing.items() if missing),
    }


def _timestamp_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
