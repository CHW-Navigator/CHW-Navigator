from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from .catalogs import (
    CatalogLoadError,
    load_phrase_bank,
    load_predicate_catalog,
    load_variable_catalog,
)
from .clinical_ir import ClinicalIRDocument
from .compare import load_patient_cases
from .dmn import DMNImportError, lint_dmn_file
from .form_ir import load_xlsform_workbook
from .lint import lint_document
from .mermaid_backend import build_mermaid_artifact, compare_mermaid_text
from .validator import validate_document
from .z3_backend import Z3BackendUnavailable, export_smt2


@dataclass(slots=True)
class StageLintIssue:
    level: str
    path: str
    message: str


@dataclass(slots=True)
class StageLintReport:
    stage: str
    artifact_type: str
    ok: bool
    issues: list[StageLintIssue] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "artifact_type": self.artifact_type,
            "ok": self.ok,
            "issues": [
                {"level": item.level, "path": item.path, "message": item.message}
                for item in self.issues
            ],
            "metadata": self.metadata,
        }


def preflight_source_artifact(kind: str, path: str | Path) -> StageLintReport:
    active_path = Path(path)
    try:
        if kind == "variable_catalog":
            raw_rows = _load_source_rows(active_path, "variables")
            variables = load_variable_catalog(active_path)
            issues = _measurement_limit_issues(raw_rows)
            return StageLintReport(
                stage="source_preflight",
                artifact_type=kind,
                ok=not any(item.level == "ERROR" for item in issues),
                issues=issues,
                metadata={"count": len(variables), "path": str(active_path)},
            )
        if kind == "predicate_catalog":
            predicates = load_predicate_catalog(active_path)
            return StageLintReport(
                stage="source_preflight",
                artifact_type=kind,
                ok=True,
                issues=[],
                metadata={"count": len(predicates), "path": str(active_path)},
            )
        if kind == "phrase_bank":
            phrases = load_phrase_bank(active_path)
            return StageLintReport(
                stage="source_preflight",
                artifact_type=kind,
                ok=True,
                issues=[],
                metadata={"count": len(phrases), "path": str(active_path)},
            )
        if kind == "dmn":
            summary = lint_dmn_file(str(active_path))
            return StageLintReport(
                stage="source_preflight",
                artifact_type=kind,
                ok=True,
                issues=[],
                metadata={**summary, "path": str(active_path)},
            )
        if kind == "patient_cases":
            cases = load_patient_cases(str(active_path))
            duplicate_names = _duplicates(case.name for case in cases)
            issues = [
                StageLintIssue("ERROR", "cases", f"duplicate case name '{name}'")
                for name in duplicate_names
            ]
            return StageLintReport(
                stage="source_preflight",
                artifact_type=kind,
                ok=not issues,
                issues=issues,
                metadata={"count": len(cases), "path": str(active_path)},
            )
    except (CatalogLoadError, DMNImportError, ValueError) as exc:
        return StageLintReport(
            stage="source_preflight",
            artifact_type=kind,
            ok=False,
            issues=[StageLintIssue("ERROR", str(active_path), str(exc))],
            metadata={"path": str(active_path)},
        )
    raise ValueError(f"unsupported source artifact kind '{kind}'")


def lint_ir_document(document: ClinicalIRDocument, *, source_path: str | None = None) -> StageLintReport:
    issues: list[StageLintIssue] = []
    for error in validate_document(document):
        issues.append(StageLintIssue("ERROR", error.path, error.message))
    for item in lint_document(document):
        issues.append(StageLintIssue(item.level, item.path, item.message))
    return StageLintReport(
        stage="compiled_ir",
        artifact_type="clinical_ir",
        ok=not any(item.level == "ERROR" for item in issues),
        issues=issues,
        metadata={"guideline_id": document.metadata.guideline_id, "source_path": source_path},
    )


def lint_xlsform_artifacts(survey_path: str | Path, choices_path: str | Path) -> StageLintReport:
    active_survey = Path(survey_path)
    active_choices = Path(choices_path)
    try:
        workbook = load_xlsform_workbook(str(active_survey), str(active_choices))
    except ValueError as exc:
        return StageLintReport(
            stage="generated_backend",
            artifact_type="xlsform",
            ok=False,
            issues=[StageLintIssue("ERROR", str(active_survey), str(exc))],
            metadata={"survey_path": str(active_survey), "choices_path": str(active_choices)},
        )
    issues: list[StageLintIssue] = []
    if not workbook.survey:
        issues.append(StageLintIssue("ERROR", "survey", "survey sheet contains no rows"))
    if not workbook.choices:
        issues.append(StageLintIssue("WARNING", "choices", "choices sheet contains no rows"))

    seen_names: set[str] = set()
    choice_lists = {row.list_name for row in workbook.choices}
    for index, row in enumerate(workbook.survey, start=2):
        if not row.name:
            issues.append(StageLintIssue("ERROR", f"survey.row[{index}]", "row is missing a name"))
            continue
        if row.name in seen_names:
            issues.append(StageLintIssue("ERROR", f"survey.{row.name}", "duplicate row name"))
        seen_names.add(row.name)
        if row.type == "calculate" and not row.calculation:
            issues.append(StageLintIssue("ERROR", f"survey.{row.name}", "calculate row is missing calculation"))
        if row.type == "note" and not row.label:
            issues.append(StageLintIssue("WARNING", f"survey.{row.name}", "note row is missing label text"))
        if row.type.startswith("select_one "):
            list_name = row.type.split(" ", 1)[1]
            if list_name not in choice_lists:
                issues.append(StageLintIssue("ERROR", f"survey.{row.name}", f"choice list '{list_name}' is missing"))

    return StageLintReport(
        stage="generated_backend",
        artifact_type="xlsform",
        ok=not any(item.level == "ERROR" for item in issues),
        issues=issues,
        metadata={
            "survey_path": str(active_survey),
            "choices_path": str(active_choices),
            "survey_rows": len(workbook.survey),
            "choice_rows": len(workbook.choices),
        },
    )


def lint_mermaid_artifact(document: ClinicalIRDocument, candidate_text: str | None = None) -> StageLintReport:
    artifact = build_mermaid_artifact(document)
    issues: list[StageLintIssue] = []
    required_snippets = [
        "flowchart ",
        "classDef variable",
        "classDef predicate",
        "classDef decision",
        "classDef output",
        "classDef rule",
    ]
    for snippet in required_snippets:
        if snippet not in artifact.text:
            issues.append(StageLintIssue("ERROR", "mermaid", f"missing required snippet '{snippet}'"))
    if candidate_text is not None:
        comparison = compare_mermaid_text(document, candidate_text)
        for mismatch in comparison.mismatches:
            issues.append(StageLintIssue("ERROR", "mermaid.compare", mismatch))
    return StageLintReport(
        stage="generated_backend",
        artifact_type="mermaid",
        ok=not any(item.level == "ERROR" for item in issues),
        issues=issues,
        metadata={"guideline_id": document.metadata.guideline_id},
    )


def lint_smt_artifact(document: ClinicalIRDocument, candidate_text: str | None = None) -> StageLintReport:
    try:
        text = candidate_text or export_smt2(document)
    except Z3BackendUnavailable as exc:
        return StageLintReport(
            stage="generated_backend",
            artifact_type="smt2",
            ok=False,
            issues=[StageLintIssue("ERROR", "smt2", str(exc))],
            metadata={"guideline_id": document.metadata.guideline_id},
        )
    issues: list[StageLintIssue] = []
    required_snippets = [
        "(declare-fun",
        "(assert",
        "(check-sat)",
    ]
    for snippet in required_snippets:
        if snippet not in text:
            issues.append(StageLintIssue("ERROR", "smt2", f"missing required snippet '{snippet}'"))
    return StageLintReport(
        stage="generated_backend",
        artifact_type="smt2",
        ok=not any(item.level == "ERROR" for item in issues),
        issues=issues,
        metadata={"guideline_id": document.metadata.guideline_id},
    )


def render_stage_lint_report(report: StageLintReport) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"


def _measurement_limit_issues(variables: dict[str, Any]) -> list[StageLintIssue]:
    issues: list[StageLintIssue] = []
    for index, row in enumerate(variables, start=1):
        variable_id = str(row.get("id", f"row_{index}"))
        variable_type = str(row.get("type", "")).strip().lower()
        if variable_type not in {"int", "decimal"}:
            continue
        measurement = row.get("measurement_limits")
        if measurement and isinstance(measurement, str):
            try:
                parsed = json.loads(measurement)
                if isinstance(parsed, dict):
                    row = {**row, **parsed}
            except JSONDecodeError:
                issues.append(
                    StageLintIssue(
                        "ERROR",
                        f"variables.{variable_id}.measurement_limits",
                        "measurement_limits must decode to a JSON object",
                    )
                )
                continue
        remeasure_min = _raw_number(row.get("remeasure_min"))
        remeasure_max = _raw_number(row.get("remeasure_max"))
        dont_allow_min = _raw_number(row.get("dont_allow_min"))
        dont_allow_max = _raw_number(row.get("dont_allow_max"))
        if (remeasure_min is None) ^ (remeasure_max is None):
            issues.append(
                StageLintIssue(
                    "ERROR",
                    f"variables.{variable_id}",
                    "remeasure_min and remeasure_max must be provided together",
                )
            )
        if (dont_allow_min is None) ^ (dont_allow_max is None):
            issues.append(
                StageLintIssue(
                    "ERROR",
                    f"variables.{variable_id}",
                    "dont_allow_min and dont_allow_max must be provided together",
                )
            )
        if remeasure_min is not None and remeasure_max is not None and remeasure_min > remeasure_max:
            issues.append(
                StageLintIssue(
                    "ERROR",
                    f"variables.{variable_id}",
                    "remeasure_min must be <= remeasure_max",
                )
            )
        if dont_allow_min is not None and dont_allow_max is not None and dont_allow_min > dont_allow_max:
            issues.append(
                StageLintIssue(
                    "ERROR",
                    f"variables.{variable_id}",
                    "dont_allow_min must be <= dont_allow_max",
                )
            )
        if (
            remeasure_min is not None
            and dont_allow_min is not None
            and remeasure_min < dont_allow_min
        ):
            issues.append(
                StageLintIssue(
                    "ERROR",
                    f"variables.{variable_id}",
                    "remeasure_min must not be lower than dont_allow_min",
                )
            )
        if (
            remeasure_max is not None
            and dont_allow_max is not None
            and remeasure_max > dont_allow_max
        ):
            issues.append(
                StageLintIssue(
                    "ERROR",
                    f"variables.{variable_id}",
                    "remeasure_max must not be higher than dont_allow_max",
                )
            )
    return issues


def _duplicates(values: Any) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def _load_source_rows(path: Path, list_key: str) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    if isinstance(data, list):
        return [dict(item) for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        rows = data.get(list_key, data.get("items", []))
        if isinstance(rows, list):
            return [dict(item) for item in rows if isinstance(item, dict)]
    return []


def _raw_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None
