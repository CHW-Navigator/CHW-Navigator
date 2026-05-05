from __future__ import annotations

import difflib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from .change_control_models import format_change_memo_error, validate_change_memo_payload
from .clinical_ir import ClinicalIRDocument
from .cht_backend import build_cht_lowering_plan, write_cht_adapter_stub
from .compare import ComparisonCase, load_patient_cases
from .evidence_utils import allocate_timestamped_dir, compiler_metadata, portable_relative_path
from .evaluator import evaluate_document
from .expr_tools import collect_refs
from .lint import LintIssue, lint_document
from .mermaid_backend import build_mermaid_artifact
from .validator import ValidationError, validate_document
from .xlsform_backend import build_xlsform, write_xlsform_csvs


class ChangeReviewBuildError(Exception):
    """Raised when a change-review package cannot be created."""


@dataclass(slots=True)
class ChangeReviewArtifacts:
    review_dir: Path
    metadata_path: Path
    readme_path: Path
    summary_path: Path
    semantic_diff_path: Path
    xlsform_diff_path: Path
    impact_map_path: Path
    workflow_burden_path: Path
    case_delta_path: Path | None


def load_change_memo(path: str | Path) -> dict[str, object]:
    memo_path = Path(path)
    try:
        raw = json.loads(memo_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ChangeReviewBuildError(f"change memo file not found: {memo_path}") from exc
    except OSError as exc:
        raise ChangeReviewBuildError(f"could not read change memo file '{memo_path}': {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ChangeReviewBuildError(
            f"change memo file '{memo_path}' is not valid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}"
        ) from exc
    try:
        return validate_change_memo_payload(raw)
    except PydanticValidationError as exc:
        raise ChangeReviewBuildError(f"change memo is invalid: {format_change_memo_error(exc)}") from exc


def create_change_review_package(
    *,
    memo: dict[str, object],
    baseline_document: ClinicalIRDocument,
    updated_document: ClinicalIRDocument,
    review_root: Path,
    baseline_ir_path: Path | None = None,
    updated_ir_path: Path | None = None,
    patient_cases_path: Path | None = None,
    baseline_dmn_path: Path | None = None,
    updated_dmn_path: Path | None = None,
) -> ChangeReviewArtifacts:
    baseline_validation = validate_document(baseline_document)
    updated_validation = validate_document(updated_document)
    baseline_lint = lint_document(baseline_document)
    updated_lint = lint_document(updated_document)

    label = str(((memo.get("metadata") or {}) if isinstance(memo, dict) else {}).get("change_id", "change-review"))
    review_root.mkdir(parents=True, exist_ok=True)
    review_dir = _allocate_review_dir(review_root, label)
    _create_review_scaffold(review_dir)

    try:
        baseline_xlsform = build_xlsform(baseline_document)
        updated_xlsform = build_xlsform(updated_document)
        baseline_mermaid = build_mermaid_artifact(baseline_document)
        updated_mermaid = build_mermaid_artifact(updated_document)
        baseline_cht = write_cht_adapter_stub(
            build_cht_lowering_plan(baseline_document, baseline_xlsform),
            review_dir / "outputs" / "baseline_cht",
        )
        updated_cht = write_cht_adapter_stub(
            build_cht_lowering_plan(updated_document, updated_xlsform),
            review_dir / "outputs" / "updated_cht",
        )

        explicit_cases: list[ComparisonCase] | None = None
        if patient_cases_path is not None:
            explicit_cases = load_patient_cases(str(patient_cases_path))

        inputs_dir = review_dir / "inputs"
        outputs_dir = review_dir / "outputs"
        review_artifacts_dir = outputs_dir / "review"
        tests_dir = review_dir / "tests"
        explicit_tests_dir = tests_dir / "explicit"
        validation_tests_dir = tests_dir / "validation"

        if baseline_ir_path is not None:
            shutil.copy2(baseline_ir_path, inputs_dir / "baseline.ir.json")
        if updated_ir_path is not None:
            shutil.copy2(updated_ir_path, inputs_dir / "updated.ir.json")
        if patient_cases_path is not None:
            shutil.copy2(patient_cases_path, inputs_dir / "patient_cases.json")
        if baseline_dmn_path is not None:
            shutil.copy2(baseline_dmn_path, inputs_dir / "baseline.dmn")
        if updated_dmn_path is not None:
            shutil.copy2(updated_dmn_path, inputs_dir / "updated.dmn")
        (inputs_dir / "change.memo.json").write_text(json.dumps(memo, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        semantic_diff = _build_semantic_diff(baseline_document, updated_document)
        semantic_diff_path = review_artifacts_dir / "semantic_diff.json"
        semantic_diff_path.write_text(json.dumps(semantic_diff, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        impact_map = _build_impact_map(baseline_document, updated_document, semantic_diff)
        impact_map_path = review_artifacts_dir / "impact_map.json"
        impact_map_path.write_text(json.dumps(impact_map, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (review_artifacts_dir / "impact_map.md").write_text(_render_impact_map_markdown(impact_map), encoding="utf-8")

        mermaid_before_path = outputs_dir / "baseline.mmd"
        mermaid_after_path = outputs_dir / "updated.mmd"
        mermaid_before_path.write_text(baseline_mermaid.text, encoding="utf-8")
        mermaid_after_path.write_text(updated_mermaid.text, encoding="utf-8")
        mermaid_delta_path = review_artifacts_dir / "mermaid_delta.md"
        mermaid_delta_path.write_text(_render_mermaid_diff(baseline_mermaid.text, updated_mermaid.text), encoding="utf-8")

        baseline_xlsform_dir = outputs_dir / "baseline_xlsform"
        updated_xlsform_dir = outputs_dir / "updated_xlsform"
        write_xlsform_csvs(baseline_xlsform, str(baseline_xlsform_dir))
        write_xlsform_csvs(updated_xlsform, str(updated_xlsform_dir))
        xlsform_diff = _build_xlsform_diff(baseline_xlsform, updated_xlsform)
        xlsform_diff_path = review_artifacts_dir / "xlsform_delta.json"
        xlsform_diff_path.write_text(json.dumps(xlsform_diff, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        xlsform_diff_md_path = review_artifacts_dir / "xlsform_delta.md"
        xlsform_diff_md_path.write_text(_render_xlsform_diff_markdown(xlsform_diff), encoding="utf-8")
        workflow_burden = _build_workflow_burden(baseline_xlsform, updated_xlsform)
        workflow_burden_path = review_artifacts_dir / "workflow_burden.json"
        workflow_burden_path.write_text(json.dumps(workflow_burden, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (review_artifacts_dir / "workflow_burden.md").write_text(
            _render_workflow_burden_markdown(workflow_burden),
            encoding="utf-8",
        )

        case_delta_path: Path | None = None
        if explicit_cases is not None:
            case_delta = _build_case_delta(baseline_document, updated_document, explicit_cases)
            case_delta_path = explicit_tests_dir / "case_delta.json"
            case_delta_path.write_text(json.dumps(case_delta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            (explicit_tests_dir / "case_delta.md").write_text(_render_case_delta_markdown(case_delta), encoding="utf-8")

        safety_report = _build_safety_report(
            baseline_validation=baseline_validation,
            updated_validation=updated_validation,
            baseline_lint=baseline_lint,
            updated_lint=updated_lint,
            semantic_diff=semantic_diff,
            workflow_burden=workflow_burden,
            case_delta=case_delta if explicit_cases is not None else None,
        )
        safety_report_path = validation_tests_dir / "safety_report.json"
        safety_report_path.write_text(json.dumps(safety_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        validation_report_path = validation_tests_dir / "validation_report.json"
        validation_report_path.write_text(
            json.dumps(
                {
                    "baseline_validation_errors": [_clean(item) for item in baseline_validation],
                    "updated_validation_errors": [_clean(item) for item in updated_validation],
                    "baseline_lint": [_clean(item) for item in baseline_lint],
                    "updated_lint": [_clean(item) for item in updated_lint],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        if baseline_dmn_path is not None and updated_dmn_path is not None:
            baseline_dmn_text = Path(baseline_dmn_path).read_text(encoding="utf-8")
            updated_dmn_text = Path(updated_dmn_path).read_text(encoding="utf-8")
            (review_artifacts_dir / "dmn_delta.md").write_text(
                _render_text_diff("baseline.dmn", baseline_dmn_text, "updated.dmn", updated_dmn_text),
                encoding="utf-8",
            )

        summary_path = review_artifacts_dir / "change_summary.md"
        summary_path.write_text(
            _render_change_summary(
                memo=memo,
                semantic_diff=semantic_diff,
                safety_report=safety_report,
                case_delta=case_delta if explicit_cases is not None else None,
            ),
            encoding="utf-8",
        )

        metadata = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "change_id": label,
            "memo_title": ((memo.get("metadata") or {}) if isinstance(memo, dict) else {}).get("title"),
            "review_dir": str(review_dir),
            "compiler": compiler_metadata(),
            "inputs": {
                "baseline_ir_path": str(baseline_ir_path) if baseline_ir_path is not None else None,
                "updated_ir_path": str(updated_ir_path) if updated_ir_path is not None else None,
                "patient_cases_path": str(patient_cases_path) if patient_cases_path is not None else None,
                "baseline_dmn_path": str(baseline_dmn_path) if baseline_dmn_path is not None else None,
                "updated_dmn_path": str(updated_dmn_path) if updated_dmn_path is not None else None,
            },
            "artifacts": {
                "semantic_diff": str(semantic_diff_path.relative_to(review_dir)),
                "impact_map": str(impact_map_path.relative_to(review_dir)),
                "change_summary": str(summary_path.relative_to(review_dir)),
                "xlsform_delta": str(xlsform_diff_path.relative_to(review_dir)),
                "workflow_burden": str(workflow_burden_path.relative_to(review_dir)),
                "baseline_cht": portable_relative_path(baseline_cht.plan_json_path, review_dir),
                "updated_cht": portable_relative_path(updated_cht.plan_json_path, review_dir),
                "safety_report": str(safety_report_path.relative_to(review_dir)),
                "validation_report": str(validation_report_path.relative_to(review_dir)),
                "case_delta": str(case_delta_path.relative_to(review_dir)) if case_delta_path is not None else None,
            },
        }
        metadata_path = review_dir / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        readme_path = review_dir / "README.md"
        readme_path.write_text(_render_review_readme(metadata), encoding="utf-8")

        return ChangeReviewArtifacts(
            review_dir=review_dir,
            metadata_path=metadata_path,
            readme_path=readme_path,
            summary_path=summary_path,
            semantic_diff_path=semantic_diff_path,
            xlsform_diff_path=xlsform_diff_path,
            impact_map_path=impact_map_path,
            workflow_burden_path=workflow_burden_path,
            case_delta_path=case_delta_path,
        )
    except Exception:
        shutil.rmtree(review_dir, ignore_errors=True)
        raise


def _allocate_review_dir(review_root: Path, label: str) -> Path:
    return allocate_timestamped_dir(review_root, label, fallback_slug="change-review")


def _create_review_scaffold(review_dir: Path) -> None:
    for relative in (
        "inputs",
        "outputs",
        "outputs/review",
        "outputs/baseline_xlsform",
        "outputs/updated_xlsform",
        "outputs/baseline_cht",
        "outputs/updated_cht",
        "tests",
        "tests/explicit",
        "tests/validation",
    ):
        (review_dir / relative).mkdir(parents=True, exist_ok=True)


def _build_semantic_diff(baseline_document: ClinicalIRDocument, updated_document: ClinicalIRDocument) -> dict[str, object]:
    baseline = _clean(baseline_document)
    updated = _clean(updated_document)
    section_diffs: dict[str, object] = {}
    for section in (
        "variables",
        "constants",
        "predicates",
        "actions",
        "phrases",
        "decisions",
        "outputs",
        "invariants",
        "phrase_bindings",
    ):
        old_values = baseline.get(section, {})
        new_values = updated.get(section, {})
        if isinstance(old_values, dict) and isinstance(new_values, dict):
            section_diffs[section] = _diff_mapping(old_values, new_values)
    section_diffs["metadata"] = {
        "baseline": baseline.get("metadata", {}),
        "updated": updated.get("metadata", {}),
        "changed": baseline.get("metadata", {}) != updated.get("metadata", {}),
    }
    return section_diffs


def _diff_mapping(old_values: dict[str, object], new_values: dict[str, object]) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    counts = {"added": 0, "removed": 0, "changed": 0, "unchanged": 0}
    for key in sorted(set(old_values) | set(new_values)):
        if key not in old_values:
            counts["added"] += 1
            entries.append({"status": "ADDED", "id": key, "updated": new_values[key]})
        elif key not in new_values:
            counts["removed"] += 1
            entries.append({"status": "REMOVED", "id": key, "baseline": old_values[key]})
        elif old_values[key] != new_values[key]:
            counts["changed"] += 1
            entries.append({"status": "CHANGED", "id": key, "baseline": old_values[key], "updated": new_values[key]})
        else:
            counts["unchanged"] += 1
            entries.append({"status": "UNCHANGED", "id": key})
    return {"counts": counts, "entries": entries}


def _build_xlsform_diff(baseline_built, updated_built) -> dict[str, object]:
    baseline_rows = {
        row.name: {
            "type": row.type,
            "label": row.label,
            "relevant": row.relevant,
            "calculation": row.calculation,
            "required": row.required,
            "constraint": row.constraint,
            "role": row.role,
        }
        for row in baseline_built.workbook.survey
    }
    updated_rows = {
        row.name: {
            "type": row.type,
            "label": row.label,
            "relevant": row.relevant,
            "calculation": row.calculation,
            "required": row.required,
            "constraint": row.constraint,
            "role": row.role,
        }
        for row in updated_built.workbook.survey
    }
    baseline_choices = {
        f"{row.list_name}:{row.name}": {
            "list_name": row.list_name,
            "name": row.name,
            "label": row.label,
        }
        for row in baseline_built.workbook.choices
    }
    updated_choices = {
        f"{row.list_name}:{row.name}": {
            "list_name": row.list_name,
            "name": row.name,
            "label": row.label,
        }
        for row in updated_built.workbook.choices
    }
    return {
        "survey_rows": _diff_mapping(baseline_rows, updated_rows),
        "choices": _diff_mapping(baseline_choices, updated_choices),
    }


def _build_workflow_burden(baseline_built, updated_built) -> dict[str, object]:
    baseline_summary = _summarize_workbook(baseline_built)
    updated_summary = _summarize_workbook(updated_built)
    deltas = {
        key: updated_summary.get(key, 0) - baseline_summary.get(key, 0)
        for key in baseline_summary
    }
    return {
        "baseline": baseline_summary,
        "updated": updated_summary,
        "delta": deltas,
    }


def _summarize_workbook(built) -> dict[str, int]:
    survey_rows = built.workbook.survey
    return {
        "survey_rows_total": len(survey_rows),
        "question_rows": sum(1 for row in survey_rows if row.type not in {"calculate", "note"}),
        "calculate_rows": sum(1 for row in survey_rows if row.type == "calculate"),
        "note_rows": sum(1 for row in survey_rows if row.type == "note"),
        "required_rows": sum(1 for row in survey_rows if row.required == "yes"),
        "yes_no_questions": sum(1 for row in survey_rows if row.type == "select_one yes_no"),
        "choice_rows": len(built.workbook.choices),
    }


def _build_case_delta(
    baseline_document: ClinicalIRDocument,
    updated_document: ClinicalIRDocument,
    patient_cases: list[ComparisonCase],
) -> dict[str, object]:
    results: list[dict[str, object]] = []
    changed_cases = 0
    for case in patient_cases:
        baseline_eval = evaluate_document(baseline_document, case.values, case.missing)
        updated_eval = evaluate_document(updated_document, case.values, case.missing)
        output_changes = _summarize_output_changes(baseline_eval.outputs, updated_eval.outputs)
        changed = bool(output_changes)
        if changed:
            changed_cases += 1
        results.append(
            {
                "name": case.name,
                "ok": not changed,
                "inputs": _clean(case.values),
                "missing": sorted(case.missing),
                "baseline_outputs": _clean(baseline_eval.outputs),
                "updated_outputs": _clean(updated_eval.outputs),
                "output_changes": output_changes,
                "mismatches": [
                    f"output '{item['output_id']}' changed from {item['baseline']} to {item['updated']}"
                    for item in output_changes
                ],
            }
        )
    return {
        "counts": {
            "total_cases": len(results),
            "changed_cases": changed_cases,
            "unchanged_cases": len(results) - changed_cases,
        },
        "cases": results,
    }


def _build_safety_report(
    *,
    baseline_validation: list[ValidationError],
    updated_validation: list[ValidationError],
    baseline_lint: list[LintIssue],
    updated_lint: list[LintIssue],
    semantic_diff: dict[str, object],
    workflow_burden: dict[str, object],
    case_delta: dict[str, object] | None,
) -> dict[str, object]:
    updated_lint_errors = [issue for issue in updated_lint if issue.level == "ERROR"]
    baseline_lint_errors = [issue for issue in baseline_lint if issue.level == "ERROR"]
    return {
        "baseline": {
            "validation_errors": [_clean(item) for item in baseline_validation],
            "lint_errors": [_clean(item) for item in baseline_lint_errors],
            "lint_warnings": [_clean(item) for item in baseline_lint if item.level == "WARNING"],
        },
        "updated": {
            "validation_errors": [_clean(item) for item in updated_validation],
            "lint_errors": [_clean(item) for item in updated_lint_errors],
            "lint_warnings": [_clean(item) for item in updated_lint if item.level == "WARNING"],
        },
        "semantic_change_counts": {
            section: details.get("counts", {})
            for section, details in semantic_diff.items()
            if isinstance(details, dict) and "counts" in details
        },
        "workflow_burden": workflow_burden,
        "case_delta_counts": case_delta.get("counts") if case_delta is not None else None,
        "release_blockers": {
            "updated_validation_errors": len(updated_validation),
            "updated_lint_errors": len(updated_lint_errors),
            "unresolved_case_changes": (case_delta or {}).get("counts", {}).get("changed_cases") if case_delta is not None else None,
        },
    }


def _build_impact_map(
    baseline_document: ClinicalIRDocument,
    updated_document: ClinicalIRDocument,
    semantic_diff: dict[str, object],
) -> dict[str, object]:
    output_producers = _output_producers(updated_document)
    decision_rule_refs = _decision_predicate_refs(updated_document)
    changed_sections = {
        section: details
        for section, details in semantic_diff.items()
        if isinstance(details, dict) and "entries" in details
    }
    predicate_impacts: list[dict[str, object]] = []
    decision_impacts: list[dict[str, object]] = []
    action_impacts: list[dict[str, object]] = []
    output_impacts: list[dict[str, object]] = []

    for entry in changed_sections.get("predicates", {}).get("entries", []):
        if not isinstance(entry, dict) or entry.get("status") == "UNCHANGED":
            continue
        predicate_id = str(entry["id"])
        consumers = sorted(
            decision_id
            for decision_id, refs in decision_rule_refs.items()
            if predicate_id in refs or predicate_id in updated_document.decisions[decision_id].inputs_used
        )
        affected_outputs = sorted(
            {
                output_id
                for decision_id in consumers
                for output_id in output_producers.get(decision_id, set())
            }
        )
        predicate_impacts.append(
            {
                "predicate_id": predicate_id,
                "status": entry.get("status"),
                "consuming_decisions": consumers,
                "affected_outputs": affected_outputs,
            }
        )

    for entry in changed_sections.get("decisions", {}).get("entries", []):
        if not isinstance(entry, dict) or entry.get("status") == "UNCHANGED":
            continue
        decision_id = str(entry["id"])
        decision = updated_document.decisions.get(decision_id)
        if decision is None:
            decision_impacts.append({"decision_id": decision_id, "status": entry.get("status")})
            continue
        decision_impacts.append(
            {
                "decision_id": decision_id,
                "status": entry.get("status"),
                "inputs_used": list(decision.inputs_used),
                "depends_on": list(decision.depends_on),
                "produced_outputs": sorted(output_producers.get(decision_id, set())),
            }
        )

    for entry in changed_sections.get("actions", {}).get("entries", []):
        if not isinstance(entry, dict) or entry.get("status") == "UNCHANGED":
            continue
        action_id = str(entry["id"])
        action = updated_document.actions.get(action_id)
        if action is None:
            action_impacts.append({"action_id": action_id, "status": entry.get("status")})
            continue
        action_impacts.append(
            {
                "action_id": action_id,
                "status": entry.get("status"),
                "kind": action.kind,
                "outputs": list(action.outputs),
                "depends_on_predicates": sorted(collect_refs(action.when, {"pred"})) if action.when else [],
                "depends_on_outputs": sorted(collect_refs(action.when, {"output"})) if action.when else [],
                "task_type": action.task_type,
            }
        )

    for entry in changed_sections.get("outputs", {}).get("entries", []):
        if not isinstance(entry, dict) or entry.get("status") == "UNCHANGED":
            continue
        output_id = str(entry["id"])
        output_impacts.append(
            {
                "output_id": output_id,
                "status": entry.get("status"),
                "producers": sorted(
                    decision_id for decision_id, produced in output_producers.items() if output_id in produced
                ),
                "phrase_binding": updated_document.phrase_bindings.get(output_id),
            }
        )

    return {
        "changed_predicates": predicate_impacts,
        "changed_decisions": decision_impacts,
        "changed_actions": action_impacts,
        "changed_outputs": output_impacts,
    }


def _decision_predicate_refs(document: ClinicalIRDocument) -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {}
    for decision_id, decision in document.decisions.items():
        decision_refs: set[str] = set()
        for rule in decision.rules:
            decision_refs |= collect_refs(rule.when, {"pred"})
            for assignment in rule.then.values():
                if isinstance(assignment, dict):
                    decision_refs |= collect_refs(assignment, {"pred"})
        refs[decision_id] = decision_refs
    return refs


def _output_producers(document: ClinicalIRDocument) -> dict[str, set[str]]:
    producers: dict[str, set[str]] = {}
    for decision_id, decision in document.decisions.items():
        produced: set[str] = set()
        for rule in decision.rules:
            produced.update(rule.then.keys())
        producers[decision_id] = produced
    return producers


def _render_change_summary(
    *,
    memo: dict[str, object],
    semantic_diff: dict[str, object],
    safety_report: dict[str, object],
    case_delta: dict[str, object] | None,
) -> str:
    metadata = memo.get("metadata", {}) if isinstance(memo, dict) else {}
    lines = [
        f"# Change Summary: {metadata.get('title', 'Untitled change')}",
        "",
        f"- Change ID: `{metadata.get('change_id', '')}`",
        f"- Change type: `{metadata.get('change_type', '')}`",
        f"- Effective date: `{metadata.get('effective_date', '')}`",
        "",
        "## Clinical Intent",
        "",
        str(memo.get("clinical_intent", "")),
        "",
        "## Scope",
        "",
    ]
    applies_to = metadata.get("applies_to", [])
    if isinstance(applies_to, list):
        lines.extend(f"- {item}" for item in applies_to)
    lines.extend(["", "## Semantic Delta Counts", ""])
    for section, details in semantic_diff.items():
        if isinstance(details, dict) and "counts" in details:
            counts = details["counts"]
            lines.append(
                f"- `{section}`: +{counts.get('added', 0)} added, {counts.get('changed', 0)} changed, {counts.get('removed', 0)} removed"
            )
    lines.extend(["", "## Workflow Burden", ""])
    burden = safety_report.get("workflow_burden", {})
    if isinstance(burden, dict):
        for key, value in burden.get("delta", {}).items():
            lines.append(f"- `{key}` delta: `{value:+d}`")
    lines.extend(["", "## Safety Gates", ""])
    blockers = safety_report.get("release_blockers", {})
    lines.append(f"- Updated validation errors: `{blockers.get('updated_validation_errors', 0)}`")
    lines.append(f"- Updated lint errors: `{blockers.get('updated_lint_errors', 0)}`")
    if case_delta is not None:
        counts = case_delta.get("counts", {})
        lines.append(f"- Changed explicit patient cases: `{counts.get('changed_cases', 0)}` of `{counts.get('total_cases', 0)}`")
    unresolved = memo.get("unresolved_questions", [])
    lines.extend(["", "## Unresolved Questions", ""])
    if isinstance(unresolved, list) and unresolved:
        lines.extend(f"- {item}" for item in unresolved)
    else:
        lines.append("- None recorded")
    return "\n".join(lines) + "\n"


def _render_mermaid_diff(baseline_text: str, updated_text: str) -> str:
    baseline_lines = _normalized_lines(baseline_text)
    updated_lines = _normalized_lines(updated_text)
    added = sorted(updated_lines - baseline_lines)
    removed = sorted(baseline_lines - updated_lines)
    lines = ["# Mermaid Delta", "", "## Added lines", ""]
    lines.extend(f"- `{line}`" for line in added) if added else lines.append("- None")
    lines.extend(["", "## Removed lines", ""])
    lines.extend(f"- `{line}`" for line in removed) if removed else lines.append("- None")
    return "\n".join(lines) + "\n"


def _render_xlsform_diff_markdown(diff: dict[str, object]) -> str:
    survey = diff.get("survey_rows", {})
    choices = diff.get("choices", {})
    lines = ["# XLSForm Delta", "", "## Survey row changes", ""]
    lines.extend(_render_diff_entries_markdown(survey))
    lines.extend(["", "## Choice-list changes", ""])
    lines.extend(_render_diff_entries_markdown(choices))
    return "\n".join(lines) + "\n"


def _render_workflow_burden_markdown(burden: dict[str, object]) -> str:
    baseline = burden.get("baseline", {}) if isinstance(burden, dict) else {}
    updated = burden.get("updated", {}) if isinstance(burden, dict) else {}
    delta = burden.get("delta", {}) if isinstance(burden, dict) else {}
    lines = ["# Workflow Burden", "", "| Metric | Baseline | Updated | Delta |", "| --- | ---: | ---: | ---: |"]
    for key in sorted(set(baseline) | set(updated) | set(delta)):
        lines.append(
            f"| `{key}` | {baseline.get(key, 0)} | {updated.get(key, 0)} | {delta.get(key, 0):+d} |"
        )
    return "\n".join(lines) + "\n"


def _render_impact_map_markdown(impact_map: dict[str, object]) -> str:
    lines = ["# Impact Map", ""]
    for section_name, label in (
        ("changed_predicates", "Changed predicates"),
        ("changed_decisions", "Changed decisions"),
        ("changed_actions", "Changed actions"),
        ("changed_outputs", "Changed outputs"),
    ):
        lines.extend([f"## {label}", ""])
        items = impact_map.get(section_name, []) if isinstance(impact_map, dict) else []
        if not items:
            lines.append("- None")
            lines.append("")
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            anchor = item.get("predicate_id") or item.get("decision_id") or item.get("action_id") or item.get("output_id")
            lines.append(f"- `{item.get('status')}` `{anchor}`")
            for key, value in item.items():
                if key in {"status", "predicate_id", "decision_id", "action_id", "output_id"}:
                    continue
                if value:
                    lines.append(f"  - `{key}`: `{value}`")
        lines.append("")
    return "\n".join(lines) + "\n"


def _render_diff_entries_markdown(section: object) -> list[str]:
    if not isinstance(section, dict):
        return ["- No data"]
    entries = section.get("entries", [])
    if not isinstance(entries, list):
        return ["- No data"]
    interesting = [entry for entry in entries if isinstance(entry, dict) and entry.get("status") != "UNCHANGED"]
    if not interesting:
        return ["- No changes"]
    lines: list[str] = []
    for entry in interesting:
        lines.append(f"- `{entry.get('status')}` `{entry.get('id')}`")
    return lines


def _render_case_delta_markdown(case_delta: dict[str, object]) -> str:
    lines = ["# Case Delta", ""]
    counts = case_delta.get("counts", {}) if isinstance(case_delta, dict) else {}
    lines.append(f"- Total cases: `{counts.get('total_cases', 0)}`")
    lines.append(f"- Changed cases: `{counts.get('changed_cases', 0)}`")
    lines.append(f"- Unchanged cases: `{counts.get('unchanged_cases', 0)}`")
    lines.extend(["", "## Changed Cases", ""])
    changed_cases = [
        item
        for item in case_delta.get("cases", [])
        if isinstance(item, dict) and not item.get("ok", True)
    ] if isinstance(case_delta, dict) else []
    if not changed_cases:
        lines.append("- None")
    else:
        for case in changed_cases:
            lines.append(f"- `{case.get('name')}`")
            for mismatch in case.get("mismatches", []):
                lines.append(f"  - {mismatch}")
    return "\n".join(lines) + "\n"


def _summarize_output_changes(
    baseline_outputs: dict[str, Any],
    updated_outputs: dict[str, Any],
) -> list[dict[str, object]]:
    changes: list[dict[str, object]] = []
    for output_id in sorted(set(baseline_outputs) | set(updated_outputs)):
        baseline_value = baseline_outputs.get(output_id, False)
        updated_value = updated_outputs.get(output_id, False)
        if baseline_value != updated_value:
            changes.append(
                {
                    "output_id": output_id,
                    "baseline": baseline_value,
                    "updated": updated_value,
                }
            )
    return changes


def _render_review_readme(metadata: dict[str, object]) -> str:
    compiler = metadata.get("compiler", {}) if isinstance(metadata, dict) else {}
    artifacts = metadata.get("artifacts", {}) if isinstance(metadata, dict) else {}
    return (
        "# Change Review Package\n\n"
        "This folder contains one immutable evidence package for a clinical change.\n\n"
        "## Provenance\n\n"
        f"- Created: `{metadata.get('created_at', '')}`\n"
        f"- Compiler version: `{compiler.get('version', 'unknown')}`\n"
        f"- Python: `{compiler.get('python', 'unknown')}`\n"
        f"- Platform: `{compiler.get('platform', 'unknown')}`\n"
        f"- Git commit: `{compiler.get('git_commit', 'unknown') or 'unknown'}`\n\n"
        "## Purpose of the tests\n\n"
        "- confirm the updated IR still validates and lints cleanly\n"
        "- show which explicit patient cases changed behavior and which stayed the same\n"
        "- make the semantic delta visible in generated artifacts such as XLSForm and Mermaid\n"
        "- preserve the exact inputs, outputs, and software version used for this review\n\n"
        "## Suggested reading order\n\n"
        "- `outputs/review/change_summary.md`\n"
        "- `outputs/review/semantic_diff.json`\n"
        "- `outputs/review/impact_map.md`\n"
        "- `outputs/review/xlsform_delta.md`\n"
        "- `outputs/review/workflow_burden.md`\n"
        f"- `{artifacts.get('baseline_cht', 'outputs/baseline_cht/cht_lowering_plan.json')}` and `{artifacts.get('updated_cht', 'outputs/updated_cht/cht_lowering_plan.json')}`\n"
        f"- `{artifacts.get('safety_report', 'tests/validation/safety_report.json')}`\n"
        f"- `{artifacts.get('validation_report', 'tests/validation/validation_report.json')}`\n"
        + (f"- `{artifacts.get('case_delta')}`\n" if artifacts.get("case_delta") else "")
    )


def _render_text_diff(before_name: str, before_text: str, after_name: str, after_text: str) -> str:
    diff = difflib.unified_diff(
        before_text.splitlines(),
        after_text.splitlines(),
        fromfile=before_name,
        tofile=after_name,
        lineterm="",
    )
    return "# Text Delta\n\n```diff\n" + "\n".join(diff) + "\n```\n"


def _normalized_lines(text: str) -> set[str]:
    return {line.strip() for line in text.splitlines() if line.strip()}


def _clean(value: object) -> object:
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, set):
        return sorted(_clean(item) for item in value)
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _clean(getattr(value, key))
            for key in value.__dataclass_fields__  # type: ignore[attr-defined]
        }
    if hasattr(value, "value"):
        return _clean(getattr(value, "value"))
    return value
