from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from .catalogs import (
    CatalogLoadError,
    compose_document_from_catalogs,
    load_phrase_bank,
    load_predicate_catalog,
    load_variable_catalog,
)
from .clinical_ir import ClinicalIRDocument
from .compare import load_patient_cases
from .dmn import DMNImportError, import_dmn_decisions, lint_dmn_file
from .expr_tools import collect_refs
from .form_ir import load_xlsform_workbook
from .lint import lint_document
from .mermaid_backend import build_mermaid_artifact, compare_mermaid_text
from .pydantic_models import format_pydantic_error, validate_patient_case_payload
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
            issues.extend(_variable_contract_issues(raw_rows))
            return StageLintReport(
                stage="source_preflight",
                artifact_type=kind,
                ok=not any(item.level == "ERROR" for item in issues),
                issues=issues,
                metadata={"count": len(variables), "path": str(active_path)},
            )
        if kind == "predicate_catalog":
            raw_rows = _load_source_rows(active_path, "predicates")
            predicates = load_predicate_catalog(active_path)
            issues = _predicate_catalog_issues(raw_rows)
            return StageLintReport(
                stage="source_preflight",
                artifact_type=kind,
                ok=not any(item.level == "ERROR" for item in issues),
                issues=issues,
                metadata={"count": len(predicates), "path": str(active_path)},
            )
        if kind == "phrase_bank":
            raw_rows = _load_source_rows(active_path, "phrases")
            phrases = load_phrase_bank(active_path)
            issues = _phrase_bank_issues(raw_rows)
            return StageLintReport(
                stage="source_preflight",
                artifact_type=kind,
                ok=not any(item.level == "ERROR" for item in issues),
                issues=issues,
                metadata={"count": len(phrases), "path": str(active_path)},
            )
        if kind == "dmn":
            summary = lint_dmn_file(str(active_path))
            issues = [
                StageLintIssue(item["level"], item["path"], item["message"])
                for item in summary.get("issues", [])
            ]
            return StageLintReport(
                stage="source_preflight",
                artifact_type=kind,
                ok=bool(summary.get("ok", True)),
                issues=issues,
                metadata={
                    "decision_count": summary.get("decision_count", 0),
                    "rule_count": summary.get("rule_count", 0),
                    "output_count": summary.get("output_count", 0),
                    "path": str(active_path),
                },
            )
        if kind == "patient_cases":
            cases = load_patient_cases(str(active_path))
            raw_payload = _load_json_payload(active_path)
            issues = _patient_case_issues(raw_payload)
            return StageLintReport(
                stage="source_preflight",
                artifact_type=kind,
                ok=not any(item.level == "ERROR" for item in issues),
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


def preflight_catalog_bundle(
    *,
    metadata_path: str | Path,
    variable_catalog_path: str | Path,
    predicate_catalog_path: str | Path,
    phrase_bank_path: str | Path,
    dmn_path: str | Path | None = None,
) -> StageLintReport:
    source_paths = {
        "metadata_path": str(Path(metadata_path)),
        "variable_catalog_path": str(Path(variable_catalog_path)),
        "predicate_catalog_path": str(Path(predicate_catalog_path)),
        "phrase_bank_path": str(Path(phrase_bank_path)),
        "dmn_path": str(Path(dmn_path)) if dmn_path is not None else None,
    }
    try:
        base_document = compose_document_from_catalogs(
            metadata_path=metadata_path,
            variable_catalog_path=variable_catalog_path,
            predicate_catalog_path=predicate_catalog_path,
            phrase_bank_path=phrase_bank_path,
        )
        document = (
            import_dmn_decisions(base_document, str(dmn_path))
            if dmn_path is not None
            else base_document
        )
    except (CatalogLoadError, DMNImportError) as exc:
        return StageLintReport(
            stage="source_crossfile",
            artifact_type="catalog_bundle",
            ok=False,
            issues=[StageLintIssue("ERROR", "catalog_bundle", str(exc))],
            metadata=source_paths,
        )

    issues = list(lint_ir_document(document).issues)
    issues.extend(_catalog_crossfile_issues(document))
    return StageLintReport(
        stage="source_crossfile",
        artifact_type="catalog_bundle",
        ok=not any(item.level == "ERROR" for item in issues),
        issues=issues,
        metadata={**source_paths, "guideline_id": document.metadata.guideline_id},
    )


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
    mermaid_text = candidate_text or artifact.text
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
    issues.extend(_mermaid_style_issues(mermaid_text))
    if candidate_text is not None:
        comparison = compare_mermaid_text(document, candidate_text)
        for mismatch in comparison.mismatches:
            issues.append(StageLintIssue("ERROR", "mermaid.compare", mismatch))
    render_ok, render_message = _lint_mermaid_render(mermaid_text)
    metadata = {
        "guideline_id": document.metadata.guideline_id,
        "render_backend": "mmdc" if shutil.which("mmdc") else "python_only",
    }
    if render_ok is False:
        issues.append(StageLintIssue("ERROR", "mermaid.render", render_message))
    elif render_message:
        issues.append(StageLintIssue("WARNING", "mermaid.render", render_message))
    return StageLintReport(
        stage="generated_backend",
        artifact_type="mermaid",
        ok=not any(item.level == "ERROR" for item in issues),
        issues=issues,
        metadata=metadata,
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


def _variable_contract_issues(rows: list[dict[str, Any]]) -> list[StageLintIssue]:
    issues: list[StageLintIssue] = []
    for index, row in enumerate(rows, start=1):
        variable_id = str(row.get("id", f"row_{index}")).strip() or f"row_{index}"
        variable_type = str(row.get("type", "")).strip().lower()
        if variable_type in {"int", "decimal"}:
            domain_min = _raw_number(row.get("domain_min"))
            domain_max = _raw_number(row.get("domain_max"))
            if not _has_domain_metadata(row):
                issues.append(
                    StageLintIssue(
                        "WARNING",
                        f"variables.{variable_id}",
                        "numeric variable should define domain metadata such as domain_min/domain_max or a domain object",
                    )
                )
            elif (domain_min is None) ^ (domain_max is None):
                issues.append(
                    StageLintIssue(
                        "WARNING",
                        f"variables.{variable_id}",
                        "numeric variable should usually provide both domain_min and domain_max together",
                    )
                )
            elif domain_min is not None and domain_max is not None and domain_min > domain_max:
                issues.append(
                    StageLintIssue(
                        "ERROR",
                        f"variables.{variable_id}",
                        "domain_min must be <= domain_max",
                    )
                )
            if variable_id.startswith("v_") and not _has_unit_hint(variable_id):
                issues.append(
                    StageLintIssue(
                        "WARNING",
                        f"variables.{variable_id}",
                        "numeric encounter variable should usually encode stored units in the identifier",
                    )
                )
            unit = str(row.get("unit", "")).strip().lower()
            if unit and not _unit_matches_identifier(variable_id, unit):
                issues.append(
                    StageLintIssue(
                        "WARNING",
                        f"variables.{variable_id}.unit",
                        f"unit '{unit}' is not clearly reflected in the identifier '{variable_id}'",
                    )
                )
            storage_unit = str(row.get("storage_unit", "")).strip().lower()
            if storage_unit and not _unit_matches_identifier(variable_id, storage_unit):
                issues.append(
                    StageLintIssue(
                        "WARNING",
                        f"variables.{variable_id}.storage_unit",
                        f"storage_unit '{storage_unit}' is not clearly reflected in the identifier '{variable_id}'",
                    )
                )
            issues.extend(_recommended_numeric_domain_issues(variable_id, domain_min, domain_max))
            if "weight" in variable_id and not _has_precision_metadata(row):
                issues.append(
                    StageLintIssue(
                        "WARNING",
                        f"variables.{variable_id}",
                        "weight variable should usually document input_decimals and display_decimals precision guidance",
                    )
                )
        if _provenance_is_sparse(row):
            issues.append(
                StageLintIssue(
                    "WARNING",
                    f"variables.{variable_id}.provenance",
                    "provenance includes source_id but no additional locator fields such as kind, row, page, section, or location",
                )
            )
    return issues


def _predicate_catalog_issues(rows: list[dict[str, Any]]) -> list[StageLintIssue]:
    issues: list[StageLintIssue] = []
    for index, row in enumerate(rows, start=1):
        predicate_id = str(row.get("id", f"row_{index}")).strip() or f"row_{index}"
        inputs_used = _split_list_like(row.get("inputs_used"))
        duplicate_inputs = _duplicates(inputs_used)
        for item in duplicate_inputs:
            issues.append(
                StageLintIssue(
                    "ERROR",
                    f"predicates.{predicate_id}.inputs_used",
                    f"duplicate inputs_used entry '{item}'",
                )
            )
        for item in inputs_used:
            if not item.startswith(("v_", "st_")):
                issues.append(
                    StageLintIssue(
                        "ERROR",
                        f"predicates.{predicate_id}.inputs_used",
                        f"inputs_used item '{item}' must start with v_ or st_",
                    )
                )
        expression = row.get("expression", row.get("expression_json"))
        if expression is None:
            continue
        try:
            expression_obj = _decode_json_object(expression, f"predicates.{predicate_id}.expression")
        except ValueError as exc:
            issues.append(StageLintIssue("ERROR", f"predicates.{predicate_id}.expression", str(exc)))
            continue
        var_refs = sorted(collect_refs(expression_obj, {"var"}))
        missing_inputs = sorted(set(var_refs) - set(inputs_used))
        extra_inputs = sorted(set(inputs_used) - set(var_refs))
        for item in missing_inputs:
            issues.append(
                StageLintIssue(
                    "ERROR",
                    f"predicates.{predicate_id}.inputs_used",
                    f"expression references variable '{item}' that is missing from inputs_used",
                )
            )
        for item in extra_inputs:
            issues.append(
                StageLintIssue(
                    "WARNING",
                    f"predicates.{predicate_id}.inputs_used",
                    f"inputs_used includes '{item}' but the expression does not reference it",
                )
            )
    return issues


def _phrase_bank_issues(rows: list[dict[str, Any]]) -> list[StageLintIssue]:
    issues: list[StageLintIssue] = []
    seen_entity_role: dict[tuple[str, str], int] = {}
    output_roles: dict[str, set[str]] = {}
    for index, row in enumerate(rows, start=1):
        key = str(row.get("key", f"row_{index}")).strip() or f"row_{index}"
        entity_id = str(row.get("entity_id") or row.get("variable_name") or "").strip()
        role = str(row.get("role", "")).strip()
        if entity_id and role:
            marker = (entity_id, role)
            if marker in seen_entity_role:
                issues.append(
                    StageLintIssue(
                        "ERROR",
                        f"phrases.{key}",
                        f"duplicate entity_id/role combination '{entity_id}' + '{role}' first seen at row {seen_entity_role[marker]}",
                    )
                )
            else:
                seen_entity_role[marker] = index
            if entity_id.startswith("o_"):
                output_roles.setdefault(entity_id, set()).add(role)
        language_map = _phrase_languages(row)
        if language_map is None:
            if not any(str(column).startswith("text_") and str(value).strip() for column, value in row.items()):
                texts = row.get("texts")
                if not (isinstance(texts, str) and "\"en\"" in texts) and not (isinstance(texts, dict) and "en" in texts):
                    issues.append(
                        StageLintIssue(
                            "WARNING",
                            f"phrases.{key}",
                            "phrase row does not include text_en; current defaults prefer English when selecting one label",
                        )
                    )
            elif not str(row.get("text_en", "")).strip():
                issues.append(
                    StageLintIssue(
                        "WARNING",
                        f"phrases.{key}",
                        "phrase row does not include text_en; current defaults prefer English when selecting one label",
                    )
                )
        else:
            if "en" not in language_map:
                issues.append(
                    StageLintIssue(
                        "WARNING",
                        f"phrases.{key}",
                        "phrase row does not include text_en; current defaults prefer English when selecting one label",
                    )
                )
            duplicate_langs = _duplicates(language_map)
            for language in duplicate_langs:
                issues.append(
                    StageLintIssue(
                        "ERROR",
                        f"phrases.{key}",
                        f"duplicate language code '{language}' after normalization",
                    )
                )
    for output_id, roles in output_roles.items():
        if "message" not in roles:
            issues.append(
                StageLintIssue(
                    "WARNING",
                    f"phrases.{output_id}",
                    "output phrase coverage is missing a message role",
                )
            )
        if "guidance" not in roles:
            issues.append(
                StageLintIssue(
                    "WARNING",
                    f"phrases.{output_id}",
                    "output phrase coverage is missing a guidance role",
                )
            )
    return issues


def _patient_case_issues(payload: Any) -> list[StageLintIssue]:
    issues: list[StageLintIssue] = []
    raw_cases = payload.get("cases", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list):
        return [StageLintIssue("ERROR", "cases", "patient case file must be a list or an object with a 'cases' list")]

    names: list[str] = []
    for index, item in enumerate(raw_cases):
        if not isinstance(item, dict):
            issues.append(StageLintIssue("ERROR", f"cases[{index}]", "case must be an object"))
            continue
        try:
            validate_patient_case_payload(item)
        except Exception as exc:
            message = str(exc)
            if hasattr(exc, "errors"):
                message = format_pydantic_error(exc)  # type: ignore[arg-type]
            issues.append(StageLintIssue("ERROR", f"cases[{index}]", message))
        name = str(item.get("name", f"case_{index + 1}"))
        names.append(name)
        raw_missing = item.get("missing", [])
        if isinstance(raw_missing, list):
            duplicate_missing = _duplicates(str(entry) for entry in raw_missing if isinstance(entry, str))
            for duplicate in duplicate_missing:
                issues.append(
                    StageLintIssue(
                        "WARNING",
                        f"cases[{index}].missing",
                        f"duplicate missing entry '{duplicate}'",
                    )
                )
    for duplicate in _duplicates(names):
        issues.append(StageLintIssue("ERROR", "cases", f"duplicate case name '{duplicate}'"))
    return issues


def _catalog_crossfile_issues(document: ClinicalIRDocument) -> list[StageLintIssue]:
    issues: list[StageLintIssue] = []
    known_variable_ids = set(document.variables)
    for predicate in document.predicates.values():
        referenced = set(predicate.inputs_used) | collect_refs(predicate.expression, {"var"})
        for variable_id in sorted(referenced):
            if variable_id not in known_variable_ids:
                issues.append(
                    StageLintIssue(
                        "ERROR",
                        f"predicates.{predicate.id}",
                        f"predicate references unknown variable '{variable_id}'",
                    )
                )

    known_entities = (
        set(document.variables)
        | set(document.predicates)
        | set(document.actions)
        | set(document.outputs)
        | set(document.decisions)
    )
    for phrase in document.phrases.values():
        if phrase.entity_id not in known_entities:
            issues.append(
                StageLintIssue(
                    "WARNING",
                    f"phrases.{phrase.key}",
                    f"phrase entity_id '{phrase.entity_id}' does not match any variable, predicate, action, output, or decision in the compiled IR",
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


def _split_list_like(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        return []
    parts = [item.strip() for item in text.replace("|", ",").split(",")]
    return [item for item in parts if item]


def _has_domain_metadata(row: dict[str, Any]) -> bool:
    return any(
        str(row.get(field, "")).strip()
        for field in ("domain", "domain_min", "domain_max", "domain_values")
    )


def _has_precision_metadata(row: dict[str, Any]) -> bool:
    return any(str(row.get(field, "")).strip() for field in ("input_decimals", "display_decimals"))


def _has_unit_hint(identifier: str) -> bool:
    hints = (
        "_g",
        "_kg",
        "_mm",
        "_cm",
        "_day",
        "_days",
        "_month",
        "_months",
        "_year",
        "_years",
        "_pct",
        "_percent",
        "_rate",
        "_count",
        "_score",
        "_x10",
        "_x100",
        "_x1000",
        "_c_x10",
        "_f_x10",
    )
    return any(hint in identifier for hint in hints)


def _unit_matches_identifier(identifier: str, unit: str) -> bool:
    normalized = unit.lower().replace(" ", "_")
    mapping = {
        "g": ("_g", "_kg_x100"),
        "gram": ("_g",),
        "grams": ("_g",),
        "kg": ("_kg", "_g", "_kg_x100"),
        "tenths_c": ("_c_x10", "_temp_c_x10"),
        "c": ("_c", "_c_x10"),
        "mm": ("_mm",),
        "cm": ("_cm", "_cm_x10"),
        "months": ("_months", "_month"),
        "days": ("_days", "_day"),
        "day_serial": ("_day", "_days"),
        "percent": ("_percent", "_pct"),
    }
    expected = mapping.get(normalized)
    if expected is None:
        return _has_unit_hint(identifier) or normalized in identifier
    return any(token in identifier for token in expected)


def _provenance_is_sparse(row: dict[str, Any]) -> bool:
    source_id = str(row.get("provenance_source_id", "")).strip()
    if not source_id:
        return False
    locator_fields = (
        "provenance_kind",
        "provenance_location",
        "provenance_row",
        "provenance_column",
        "provenance_table",
        "provenance_page",
        "provenance_section",
        "provenance_note",
    )
    return not any(str(row.get(field, "")).strip() for field in locator_fields)


def _recommended_numeric_domain_issues(
    variable_id: str,
    domain_min: float | int | None,
    domain_max: float | int | None,
) -> list[StageLintIssue]:
    if domain_min is None or domain_max is None:
        return []
    recommendation = _recommended_numeric_domain(variable_id)
    if recommendation is None:
        return []
    recommended_min, recommended_max, rationale = recommendation
    issues: list[StageLintIssue] = []
    if domain_min > recommended_min or domain_max < recommended_max:
        issues.append(
            StageLintIssue(
                "WARNING",
                f"variables.{variable_id}.domain",
                f"declared domain [{domain_min}, {domain_max}] is narrower than the recommended broad proof domain [{recommended_min}, {recommended_max}] for {rationale}",
            )
        )
    return issues


def _recommended_numeric_domain(variable_id: str) -> tuple[int, int, str] | None:
    identifier = variable_id.lower()
    if "temp" in identifier and "_x10" in identifier:
        return (250, 450, "temperature stored in tenths of degrees Celsius")
    if "resp_rate" in identifier or "respiratory_rate" in identifier:
        return (0, 250, "respiratory rate")
    if "weight" in identifier and "_g" in identifier:
        return (50, 200000, "weight stored in grams")
    if "weight" in identifier and "_kg_x100" in identifier:
        return (5, 20000, "weight stored as kg x 100")
    if "height" in identifier and "_mm" in identifier:
        return (200, 2500, "length/height stored in millimeters")
    if "age" in identifier and "_day" in identifier:
        return (0, 3650, "age stored in days")
    if ("duration" in identifier or identifier.endswith("_days")) and "_day" in identifier:
        return (0, 3650, "symptom duration stored in days")
    if "stools" in identifier and ("_count" in identifier or "_day" in identifier):
        return (0, 100, "stools per day count")
    if "vomit" in identifier and ("_count" in identifier or "_day" in identifier):
        return (0, 100, "vomits per day count")
    if "muac" in identifier and "_mm" in identifier:
        return (50, 300, "MUAC stored in millimeters")
    if "spo2" in identifier or "spo_2" in identifier:
        return (0, 100, "oxygen saturation percent")
    if any(token in identifier for token in ("waz", "haz", "whz", "wlz", "baz")) and "_x10" in identifier:
        return (-100, 100, "z-score stored in tenths")
    return None


def _phrase_languages(row: dict[str, Any]) -> list[str] | None:
    languages: list[str] = []
    for column, value in row.items():
        if not isinstance(column, str) or not column.startswith("text_"):
            continue
        if not str(value).strip():
            continue
        languages.append(column[5:].strip().lower())
    if languages:
        return languages
    texts = row.get("texts")
    if isinstance(texts, dict):
        return [str(key).strip().lower() for key, value in texts.items() if str(value).strip()]
    if isinstance(texts, str) and texts.strip():
        try:
            parsed = json.loads(texts)
        except JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return [str(key).strip().lower() for key, value in parsed.items() if str(value).strip()]
    return None


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


def _load_json_payload(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}") from exc


def _decode_json_object(value: Any, label: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a JSON object or JSON string")
    try:
        parsed = json.loads(value)
    except JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must decode to a JSON object")
    return parsed


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


def _mermaid_style_issues(text: str) -> list[StageLintIssue]:
    issues: list[StageLintIssue] = []
    stripped = text.strip()
    if "graph " not in stripped and "flowchart " not in stripped:
        issues.append(StageLintIssue("ERROR", "mermaid", "missing graph declaration"))
    if "-->" not in text and "-.->" not in text and "==>" not in text:
        issues.append(StageLintIssue("ERROR", "mermaid", "no edges defined"))
    if text.count("{") != text.count("}"):
        issues.append(StageLintIssue("ERROR", "mermaid", "unbalanced braces"))
    if text.count("[") != text.count("]"):
        issues.append(StageLintIssue("ERROR", "mermaid", "unbalanced square brackets"))
    if "classDef " not in text:
        issues.append(StageLintIssue("WARNING", "mermaid", "no class definitions found"))
    return issues


def _lint_mermaid_render(text: str) -> tuple[bool | None, str]:
    mmdc_path = shutil.which("mmdc")
    if not mmdc_path:
        return None, "Mermaid CLI (mmdc) is not installed; skipped render validation"

    mermaid_file = None
    svg_file = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mmd", mode="w", encoding="utf-8") as handle:
            handle.write(text)
            mermaid_file = handle.name
        svg_file = mermaid_file + ".svg"
        result = subprocess.run(
            [mmdc_path, "-i", mermaid_file, "-o", svg_file],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            detail = stderr or stdout or f"mmdc exited with code {result.returncode}"
            return False, detail
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "Mermaid CLI render timed out"
    except OSError as exc:
        return False, f"Mermaid CLI render failed: {exc}"
    finally:
        for path in (mermaid_file, svg_file):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
