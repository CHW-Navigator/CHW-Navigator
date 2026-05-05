from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .clinical_ir import (
    ClinicalIRDocument,
    DecisionDef,
    Domain,
    HitPolicy,
    Metadata,
    MissingnessPolicy,
    OutputDef,
    PhraseDef,
    PhraseRole,
    PredicateDef,
    ProvenanceRecord,
    RuleDef,
    ScalarType,
    VariableDef,
)
from .form_ir import SurveyRow, XLSFormWorkbook, load_xlsform_workbook
from .validator import validate_document
from .xlsform_expr import XLSFormExpressionError, parse_xlsform_expression


class XLSFormImportError(Exception):
    """Raised when an XLSForm workbook is outside the supported import subset."""


@dataclass(slots=True)
class XLSFormImportFinding:
    status: str
    row: int | None
    field: str
    message: str
    original_name: str | None = None
    canonical_name: str | None = None


@dataclass(slots=True)
class XLSFormImportReport:
    findings: list[XLSFormImportFinding] = field(default_factory=list)
    name_map: dict[str, str] = field(default_factory=dict)

    def add(
        self,
        *,
        status: str,
        row: int | None,
        field: str,
        message: str,
        original_name: str | None = None,
        canonical_name: str | None = None,
    ) -> None:
        self.findings.append(
            XLSFormImportFinding(
                status=status,
                row=row,
                field=field,
                message=message,
                original_name=original_name,
                canonical_name=canonical_name,
            )
        )


@dataclass(slots=True)
class ImportedXLSForm:
    document: ClinicalIRDocument
    workbook: XLSFormWorkbook
    report: XLSFormImportReport = field(default_factory=XLSFormImportReport)


_REFERENCE_RE = re.compile(r"\$\{([^}]+)\}")


def import_xlsform_files(
    survey_path: str,
    choices_path: str,
    *,
    guideline_id: str | None = None,
    default_predicate_missingness: MissingnessPolicy = MissingnessPolicy.REQUIRE_INPUTS,
) -> ClinicalIRDocument:
    workbook = load_xlsform_workbook(survey_path, choices_path)
    imported = import_xlsform_workbook(
        workbook,
        survey_path=survey_path,
        choices_path=choices_path,
        guideline_id=guideline_id,
        default_predicate_missingness=default_predicate_missingness,
    )
    return imported.document


def import_xlsform_files_detailed(
    survey_path: str,
    choices_path: str,
    *,
    guideline_id: str | None = None,
    default_predicate_missingness: MissingnessPolicy = MissingnessPolicy.REQUIRE_INPUTS,
) -> ImportedXLSForm:
    workbook = load_xlsform_workbook(survey_path, choices_path)
    return import_xlsform_workbook(
        workbook,
        survey_path=survey_path,
        choices_path=choices_path,
        guideline_id=guideline_id,
        default_predicate_missingness=default_predicate_missingness,
    )


def import_xlsform_workbook(
    workbook: XLSFormWorkbook,
    *,
    survey_path: str | None = None,
    choices_path: str | None = None,
    guideline_id: str | None = None,
    default_predicate_missingness: MissingnessPolicy = MissingnessPolicy.REQUIRE_INPUTS,
) -> ImportedXLSForm:
    workbook, report = _normalize_workbook(workbook, survey_path=survey_path)
    metadata = Metadata(
        ir_version=1,
        guideline_id=guideline_id or workbook.form_id or workbook.title or "xlsform_import",
        sources=[
            {
                "source_id": survey_path or workbook.form_id or workbook.title or "xlsform_survey",
                "kind": "xlsform_survey",
            },
            {
                "source_id": choices_path or workbook.form_id or workbook.title or "xlsform_choices",
                "kind": "xlsform_choices",
            },
        ],
    )
    choices_by_list: dict[str, list[str]] = {}
    for choice in workbook.choices:
        choices_by_list.setdefault(choice.list_name, []).append(choice.name)

    variables: dict[str, VariableDef] = {}
    predicates: dict[str, PredicateDef] = {}
    outputs: dict[str, OutputDef] = {}
    phrases: dict[str, PhraseDef] = {}
    decisions: dict[str, DecisionDef] = {}

    calc_rows: dict[str, SurveyRow] = {}
    calc_asts: dict[str, dict[str, Any]] = {}
    row_order: list[str] = []

    for index, row in enumerate(workbook.survey):
        row_provenance = [_row_provenance(survey_path, index + 2, row.name or f"row_{index + 1}")]
        if row.type == "note":
            _import_note_row(row, phrases, row_provenance)
            continue
        if row.type == "calculate":
            if not row.calculation:
                raise XLSFormImportError(f"calculate row '{row.name}' is missing a calculation")
            try:
                calc_asts[row.name] = parse_xlsform_expression(row.calculation)
            except XLSFormExpressionError as exc:
                raise XLSFormImportError(f"calculate row '{row.name}' has unsupported expression: {exc}") from exc
            calc_rows[row.name] = row
            row_order.append(row.name)
            continue
        if row.relevant:
            raise XLSFormImportError(
                f"question row '{row.name}' uses relevant logic, which is not yet supported by the XLSForm importer"
            )
        if row.constraint:
            raise XLSFormImportError(
                f"question row '{row.name}' uses constraint logic, which is not yet supported by the XLSForm importer"
            )
        variables[row.name] = _import_variable_row(row, choices_by_list, row_provenance)
        if row.label and row.label != row.name:
            phrase_key = f"m_{row.name}"
            phrases[phrase_key] = PhraseDef(
                key=phrase_key,
                entity_id=row.name,
                role=PhraseRole.LABEL,
                texts={"en": row.label},
                provenance=row_provenance,
            )

    variable_ids = set(variables)
    predicate_row_names = [name for name in row_order if name.startswith("p_")]
    rule_row_names = [name for name in row_order if name.startswith("rh_")]
    state_row_names = [name for name in row_order if name.startswith("state__")]
    output_row_names = [name for name in row_order if name.startswith("o_")]
    state_alias_map = {name: _state_output_id(name) for name in state_row_names}
    standalone_calc_output_rows = [
        name for name in row_order
        if name.startswith("o_") and name not in state_row_names and name not in predicate_row_names
    ]

    for name in predicate_row_names:
        expression_ast = calc_asts[name]
        normalized_expr, inferred_policy = _normalize_predicate_expression(expression_ast)
        symbol_types = _symbol_type_map(variables=variables, predicate_ids=set(predicates), outputs={})
        predicates[name] = PredicateDef(
            id=name,
            inputs_used=sorted(_collect_var_refs(normalized_expr)),
            expression=_resolve_refs(
                normalized_expr,
                variable_ids,
                set(predicates),
                set(outputs),
                symbol_types=symbol_types,
                state_alias_map=state_alias_map,
                allow_temporaries=False,
            ),
            missingness_policy=inferred_policy or default_predicate_missingness,
            provenance=[_row_provenance(survey_path, _row_number(workbook, name), name)],
        )

    decision_specs = _reconstruct_decisions(
        workbook=workbook,
        calc_asts=calc_asts,
        row_order=row_order,
        variable_ids=variable_ids,
        predicate_ids=set(predicates),
        state_row_names=state_row_names,
        output_row_names=output_row_names,
        standalone_calc_output_rows=standalone_calc_output_rows,
    )

    for output_id, spec in decision_specs["outputs"].items():
        outputs[output_id] = OutputDef(
            id=output_id,
            type=spec,
            provenance=[_row_provenance(survey_path, _row_number(workbook, output_id), output_id)],
        )

    for decision in decision_specs["decisions"]:
        canonical_rules: list[RuleDef] = []
        symbol_types = _symbol_type_map(variables=variables, predicate_ids=set(predicates), outputs=outputs)
        for rule_id, when_expr, then_map in decision["rules"]:
            canonical_then = {
                output_id: _resolve_assignment_refs(
                    value,
                    variable_ids,
                    set(predicates),
                    set(outputs),
                    symbol_types=symbol_types,
                    state_alias_map=state_alias_map,
                )
                for output_id, value in then_map.items()
            }
            canonical_when = _resolve_refs(
                when_expr,
                variable_ids,
                set(predicates),
                set(outputs),
                symbol_types=symbol_types,
                state_alias_map=state_alias_map,
                allow_temporaries=False,
            )
            canonical_rules.append(
                RuleDef(
                    id=rule_id,
                    when=canonical_when,
                    then=canonical_then,
                    provenance=[_row_provenance(survey_path, _row_number(workbook, f"rh_{rule_id}"), rule_id)],
                )
            )
        decisions[decision["id"]] = DecisionDef(
            id=decision["id"],
            hit_policy=HitPolicy.FIRST,
            rules=canonical_rules,
            provenance=[_row_provenance(survey_path, decision["row"], decision["id"])],
        )

    document = ClinicalIRDocument(
        metadata=metadata,
        variables=variables,
        predicates=predicates,
        phrases=phrases,
        decisions=decisions,
        outputs=outputs,
    )
    errors = validate_document(document)
    if errors:
        message = "; ".join(f"{item.path}: {item.message}" for item in errors)
        raise XLSFormImportError(f"imported XLSForm does not satisfy the supported Clinical IR subset: {message}")
    return ImportedXLSForm(document=document, workbook=workbook, report=report)


def _import_variable_row(
    row: SurveyRow,
    choices_by_list: dict[str, list[str]],
    provenance: list[ProvenanceRecord],
) -> VariableDef:
    row_type = row.type.strip()
    allowed_missingness = row.required.strip() != "true()"
    if row_type == "integer":
        return VariableDef(id=row.name, type=ScalarType.INT, allowed_missingness=allowed_missingness, provenance=provenance)
    if row_type == "decimal":
        return VariableDef(id=row.name, type=ScalarType.DECIMAL, allowed_missingness=allowed_missingness, provenance=provenance)
    if row_type == "text":
        return VariableDef(id=row.name, type=ScalarType.STRING, allowed_missingness=allowed_missingness, provenance=provenance)
    if row_type == "select_one yes_no":
        return VariableDef(id=row.name, type=ScalarType.BOOL, allowed_missingness=allowed_missingness, provenance=provenance)
    if row_type.startswith("select_one "):
        list_name = row_type.split(" ", 1)[1].strip()
        choices = choices_by_list.get(list_name)
        if not choices:
            raise XLSFormImportError(f"enum question '{row.name}' references unknown choice list '{list_name}'")
        return VariableDef(
            id=row.name,
            type=ScalarType.ENUM,
            domain=Domain(values=choices),
            allowed_missingness=allowed_missingness,
            provenance=provenance,
        )
    raise XLSFormImportError(f"unsupported XLSForm question type '{row.type}' for row '{row.name}'")


def _normalize_workbook(
    workbook: XLSFormWorkbook,
    *,
    survey_path: str | None,
) -> tuple[XLSFormWorkbook, XLSFormImportReport]:
    report = XLSFormImportReport()
    note_gate_targets = {
        output_id
        for row in workbook.survey
        if row.type == "note"
        for output_id in [_extract_single_gate_ref(row.relevant)]
        if output_id is not None
    }

    alias_map: dict[str, str] = {}
    normalized_rows: list[SurveyRow] = []
    used_names: dict[str, int] = {}
    original_names_by_canonical: dict[str, str] = {}

    parsed_calculations: dict[str, dict[str, Any] | None] = {}
    for row in workbook.survey:
        if row.type == "calculate" and row.calculation:
            try:
                parsed_calculations[row.name] = parse_xlsform_expression(row.calculation)
            except XLSFormExpressionError:
                parsed_calculations[row.name] = None

    for index, row in enumerate(workbook.survey, start=2):
        canonical_name = row.name
        if row.type == "note":
            canonical_name = row.name or f"note_{index - 1}"
        elif row.type == "calculate":
            canonical_name = _canonical_calculate_name(
                row.name,
                parsed_calculations.get(row.name),
                note_gate_targets=note_gate_targets,
            )
        else:
            canonical_name = _canonical_variable_name(row.name)

        canonical_name = canonical_name or f"row_{index - 1}"
        prior_original = original_names_by_canonical.get(canonical_name)
        if canonical_name in used_names and prior_original != row.name:
            first_row = used_names[canonical_name]
            report.add(
                status="error",
                row=index,
                field="name",
                message=f"row name '{row.name}' normalizes to '{canonical_name}', which already belongs to row {first_row}",
                original_name=row.name,
                canonical_name=canonical_name,
            )
            raise XLSFormImportError(
                f"XLSForm row '{row.name}' at line {index} collides with another row after canonical normalization to '{canonical_name}'"
            )
        if row.name and row.name != canonical_name:
            report.name_map[row.name] = canonical_name
            report.add(
                status="normalized",
                row=index,
                field="name",
                message=f"normalized XLSForm row name '{row.name}' to canonical identifier '{canonical_name}'",
                original_name=row.name,
                canonical_name=canonical_name,
            )
        used_names.setdefault(canonical_name, index)
        original_names_by_canonical.setdefault(canonical_name, row.name)
        alias_map[row.name] = canonical_name
        normalized_rows.append(
            SurveyRow(
                type=row.type,
                name=canonical_name,
                label=row.label,
                relevant=row.relevant,
                calculation=row.calculation,
                required=row.required,
                constraint=row.constraint,
                role=row.role,
            )
        )

    rewritten_rows: list[SurveyRow] = []
    for index, row in enumerate(normalized_rows, start=2):
        rewritten_relevant = _rewrite_references(row.relevant, alias_map)
        rewritten_calculation = _rewrite_references(row.calculation, alias_map)
        rewritten_label = _rewrite_references(row.label, alias_map)
        if rewritten_relevant != row.relevant:
            report.add(
                status="warning",
                row=index,
                field="relevant",
                message=f"rewrote XLSForm relevant references for row '{row.name}' to use canonical identifiers",
                original_name=row.name,
                canonical_name=row.name,
            )
        if rewritten_calculation != row.calculation:
            report.add(
                status="warning",
                row=index,
                field="calculation",
                message=f"rewrote XLSForm calculation references for row '{row.name}' to use canonical identifiers",
                original_name=row.name,
                canonical_name=row.name,
            )
        if rewritten_label != row.label:
            report.add(
                status="warning",
                row=index,
                field="label",
                message=f"rewrote embedded XLSForm label references for row '{row.name}' to use canonical identifiers",
                original_name=row.name,
                canonical_name=row.name,
            )
        rewritten_rows.append(
            SurveyRow(
                type=row.type,
                name=row.name,
                label=rewritten_label,
                relevant=rewritten_relevant,
                calculation=rewritten_calculation,
                required=row.required,
                constraint=row.constraint,
                role=row.role,
            )
        )

    return XLSFormWorkbook(
        title=workbook.title,
        form_id=workbook.form_id,
        survey=rewritten_rows,
        choices=list(workbook.choices),
    ), report


def _canonical_variable_name(name: str) -> str:
    stripped = name.strip()
    if stripped.startswith(("v_", "st_")):
        return stripped
    return f"v_{_slugify_identifier(stripped)}"


def _canonical_calculate_name(
    name: str,
    parsed_expression: dict[str, Any] | None,
    *,
    note_gate_targets: set[str],
) -> str:
    stripped = name.strip()
    if stripped.startswith(("p_", "rh_", "state__", "o_")):
        return stripped
    if stripped in note_gate_targets:
        return f"o_{_slugify_identifier(stripped)}"
    inferred_type = _infer_value_type(parsed_expression or {"kind": "literal", "value": ""}, {})
    if inferred_type is ScalarType.BOOL:
        return f"p_{_slugify_identifier(stripped)}"
    return f"o_{_slugify_identifier(stripped)}"


def _slugify_identifier(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", name.strip())
    slug = re.sub(r"_+", "_", slug).strip("_").lower()
    return slug or "field"


def _rewrite_references(text: str, alias_map: dict[str, str]) -> str:
    if not text:
        return text

    def replace(match: re.Match[str]) -> str:
        original = match.group(1)
        return "${" + alias_map.get(original, original) + "}"

    return _REFERENCE_RE.sub(replace, text)


def _import_note_row(row: SurveyRow, phrases: dict[str, PhraseDef], provenance: list[ProvenanceRecord]) -> None:
    output_id = _extract_output_gate(row.relevant)
    if output_id is None:
        return
    role = PhraseRole.GUIDANCE if row.name.startswith("guidance_") else PhraseRole.MESSAGE
    key = row.label if row.label.startswith("m_") else f"m_{row.name}"
    texts = {} if row.label.startswith("m_") else {"en": row.label}
    phrases[key] = PhraseDef(key=key, entity_id=output_id, role=role, texts=texts or {"en": row.label}, provenance=provenance)


def _extract_output_gate(relevant: str) -> str | None:
    output_id = _extract_single_gate_ref(relevant)
    if output_id is not None and output_id.startswith("o_"):
        return output_id
    return None


def _extract_single_gate_ref(relevant: str) -> str | None:
    text = relevant.strip()
    if text.startswith("${") and text.endswith("}"):
        return text[2:-1]
    return None


def _normalize_predicate_expression(expr: dict[str, Any]) -> tuple[dict[str, Any], MissingnessPolicy | None]:
    if _is_boolean_if_wrapper(expr):
        return expr["cond"], MissingnessPolicy.TREAT_MISSING_AS_FALSE
    return expr, None


def _reconstruct_decisions(
    *,
    workbook: XLSFormWorkbook,
    calc_asts: dict[str, dict[str, Any]],
    row_order: list[str],
    variable_ids: set[str],
    predicate_ids: set[str],
    state_row_names: list[str],
    output_row_names: list[str],
    standalone_calc_output_rows: list[str],
) -> dict[str, Any]:
    outputs: dict[str, ScalarType] = {}
    decisions: list[dict[str, Any]] = []
    used_rule_rows: set[str] = set()

    grouped_state_rows: dict[str, list[str]] = {}
    for state_row in state_row_names:
        _, output_id, decision_id = state_row.split("__", 2)
        grouped_state_rows.setdefault(decision_id, []).append(state_row)

    for decision_id, rows in grouped_state_rows.items():
        referenced_rule_rows: list[str] = []
        for row_name in rows:
            _collect_rule_row_refs(calc_asts[row_name], referenced_rule_rows)
            outputs[_state_output_id(row_name)] = _infer_output_type_from_state(calc_asts[row_name], calc_asts)
        ordered_rule_rows = [name for name in row_order if name in referenced_rule_rows]
        if not ordered_rule_rows:
            raise XLSFormImportError(f"could not infer any rule rows for decision '{decision_id}'")
        decision_row_number = _row_number_by_name(workbook, rows[0])
        decisions.append(
            {
                "id": decision_id,
                "row": decision_row_number,
                "rules": _reconstruct_rules_for_decision(
                    decision_id=decision_id,
                    rule_row_names=ordered_rule_rows,
                    state_rows=rows,
                    calc_asts=calc_asts,
                    variable_ids=variable_ids,
                    predicate_ids=predicate_ids,
                ),
            }
        )
        used_rule_rows.update(ordered_rule_rows)

    standalone_output_rows = [
        name for name in output_row_names
        if _row_references_rule_rows(calc_asts.get(name)) and not _row_references_state_rows(calc_asts.get(name))
    ]
    if standalone_output_rows:
        referenced_rule_rows: list[str] = []
        for row_name in standalone_output_rows:
            _collect_rule_row_refs(calc_asts[row_name], referenced_rule_rows)
            outputs[row_name] = _infer_output_type_from_state(calc_asts[row_name], calc_asts)
        ordered_rule_rows = [name for name in row_order if name in referenced_rule_rows]
        decisions.append(
            {
                "id": "d_imported_xlsform",
                "row": _row_number_by_name(workbook, standalone_output_rows[0]),
                "rules": _reconstruct_rules_for_decision(
                    decision_id="d_imported_xlsform",
                    rule_row_names=ordered_rule_rows,
                    state_rows=standalone_output_rows,
                    calc_asts=calc_asts,
                    variable_ids=variable_ids,
                    predicate_ids=predicate_ids,
                    direct_output_rows=True,
                ),
            }
        )
        used_rule_rows.update(ordered_rule_rows)

    direct_expression_outputs = [
        name for name in standalone_calc_output_rows
        if name not in outputs and not _row_references_rule_rows(calc_asts.get(name))
    ]
    if direct_expression_outputs:
        for output_row_name in direct_expression_outputs:
            outputs[output_row_name] = _infer_output_type_from_output_row(calc_asts.get(output_row_name), calc_asts, outputs)
        then_map = {
            output_row_name: calc_asts[output_row_name]
            for output_row_name in direct_expression_outputs
        }
        decisions.append(
            {
                "id": "d_imported_calculations",
                "row": _row_number_by_name(workbook, direct_expression_outputs[0]),
                "rules": [
                    (
                        "r_imported_output_calculations",
                        {"kind": "else"},
                        then_map,
                    )
                ],
            }
        )

    orphan_rule_rows = [name for name in row_order if name.startswith("rh_") and name not in used_rule_rows]
    if orphan_rule_rows:
        raise XLSFormImportError(
            f"unsupported XLSForm rule-hit rows could not be assigned to any imported decision: {orphan_rule_rows}"
        )

    for output_row_name in output_row_names:
        outputs.setdefault(output_row_name, _infer_output_type_from_output_row(calc_asts.get(output_row_name), calc_asts, outputs))

    return {"outputs": outputs, "decisions": decisions}


def _reconstruct_rules_for_decision(
    *,
    decision_id: str,
    rule_row_names: list[str],
    state_rows: list[str],
    calc_asts: dict[str, dict[str, Any]],
    variable_ids: set[str],
    predicate_ids: set[str],
    direct_output_rows: bool = False,
) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    previous_rule_rows: list[str] = []
    rules: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for rule_row_name in rule_row_names:
        rule_id = rule_row_name[len("rh_") :]
        raw_expr = calc_asts[rule_row_name]
        condition = _unwrap_boolean_if(raw_expr)
        stripped_condition = _strip_prior_rule_gating(condition, previous_rule_rows)
        if _is_else_from_prior_terms(condition, previous_rule_rows):
            stripped_condition = {"kind": "else"}
        then_map: dict[str, Any] = {}
        for state_row_name in state_rows:
            output_id = state_row_name if direct_output_rows else _state_output_id(state_row_name)
            assignments = _collect_assignments_for_rule(calc_asts[state_row_name], calc_asts)
            if rule_row_name in assignments:
                then_map[output_id] = assignments[rule_row_name]
        if not then_map:
            raise XLSFormImportError(f"rule '{rule_id}' in decision '{decision_id}' never assigns any output")
        rules.append((rule_id, stripped_condition, then_map))
        previous_rule_rows.append(rule_row_name)
    return rules


def _collect_assignments_for_rule(expr: dict[str, Any], calc_asts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    assignments: dict[str, Any] = {}
    current = expr
    while current.get("kind") == "if":
        cond = current["cond"]
        if cond.get("kind") != "ref" or not str(cond.get("id", "")).startswith("rh_"):
            raise XLSFormImportError("state/output row uses unsupported non-rule condition in nested if chain")
        assignments[str(cond["id"])] = current["then"]
        current = current["else"]
    return assignments


def _strip_prior_rule_gating(expr: dict[str, Any], previous_rule_rows: list[str]) -> dict[str, Any]:
    if not previous_rule_rows:
        return expr
    terms = _flatten_and(expr)
    kept: list[dict[str, Any]] = []
    for term in terms:
        if _is_negated_prior_rule_ref(term, previous_rule_rows):
            continue
        kept.append(term)
    if not kept:
        return {"kind": "else"}
    if len(kept) == 1:
        return kept[0]
    return {"kind": "and", "args": kept}


def _is_else_from_prior_terms(expr: dict[str, Any], previous_rule_rows: list[str]) -> bool:
    if not previous_rule_rows:
        return False
    terms = _flatten_and(expr)
    return bool(terms) and all(_is_negated_prior_rule_ref(term, previous_rule_rows) for term in terms)


def _flatten_and(expr: dict[str, Any]) -> list[dict[str, Any]]:
    if expr.get("kind") != "and":
        return [expr]
    items: list[dict[str, Any]] = []
    for arg in expr["args"]:
        items.extend(_flatten_and(arg))
    return items


def _is_negated_prior_rule_ref(expr: dict[str, Any], previous_rule_rows: list[str]) -> bool:
    return (
        expr.get("kind") == "not"
        and expr.get("arg", {}).get("kind") == "ref"
        and expr["arg"]["id"] in previous_rule_rows
    )


def _unwrap_boolean_if(expr: dict[str, Any]) -> dict[str, Any]:
    if _is_boolean_if_wrapper(expr):
        return expr["cond"]
    return expr


def _is_boolean_if_wrapper(expr: dict[str, Any]) -> bool:
    return (
        expr.get("kind") == "if"
        and expr.get("then", {}).get("kind") == "literal"
        and expr["then"].get("value") is True
        and expr.get("else", {}).get("kind") == "literal"
        and expr["else"].get("value") is False
    )


def _collect_rule_row_refs(expr: dict[str, Any], collector: list[str]) -> None:
    if expr is None:
        return
    if expr.get("kind") == "ref" and str(expr.get("id", "")).startswith("rh_"):
        name = str(expr["id"])
        if name not in collector:
            collector.append(name)
        return
    for key in ("arg", "left", "right", "cond", "then", "else", "target"):
        child = expr.get(key)
        if isinstance(child, dict):
            _collect_rule_row_refs(child, collector)
    for child in expr.get("args", []):
        if isinstance(child, dict):
            _collect_rule_row_refs(child, collector)


def _row_references_rule_rows(expr: dict[str, Any] | None) -> bool:
    if expr is None:
        return False
    if expr.get("kind") == "ref" and str(expr.get("id", "")).startswith("rh_"):
        return True
    for key in ("arg", "left", "right", "cond", "then", "else", "target"):
        child = expr.get(key)
        if isinstance(child, dict) and _row_references_rule_rows(child):
            return True
    return any(isinstance(child, dict) and _row_references_rule_rows(child) for child in expr.get("args", []))


def _row_references_state_rows(expr: dict[str, Any] | None) -> bool:
    if expr is None:
        return False
    if expr.get("kind") == "ref" and str(expr.get("id", "")).startswith("state__"):
        return True
    for key in ("arg", "left", "right", "cond", "then", "else", "target"):
        child = expr.get(key)
        if isinstance(child, dict) and _row_references_state_rows(child):
            return True
    return any(isinstance(child, dict) and _row_references_state_rows(child) for child in expr.get("args", []))


def _infer_output_type_from_state(expr: dict[str, Any], calc_asts: dict[str, dict[str, Any]]) -> ScalarType:
    for value in _collect_assignments_for_rule(expr, calc_asts).values():
        inferred = _infer_value_type(value, calc_asts)
        if inferred is not None:
            return inferred
    return ScalarType.BOOL


def _infer_output_type_from_output_row(
    expr: dict[str, Any] | None,
    calc_asts: dict[str, dict[str, Any]],
    known_outputs: dict[str, ScalarType],
) -> ScalarType:
    if expr is None:
        return ScalarType.BOOL
    if expr.get("kind") == "ref" and str(expr.get("id", "")).startswith("state__"):
        state_expr = calc_asts.get(str(expr["id"]))
        if state_expr is not None:
            return _infer_output_type_from_state(state_expr, calc_asts)
    inferred = _infer_value_type(expr, calc_asts)
    return inferred or known_outputs.get(str(expr.get("id", "")), ScalarType.BOOL)


def _infer_value_type(expr: dict[str, Any], calc_asts: dict[str, dict[str, Any]]) -> ScalarType | None:
    kind = expr.get("kind")
    if kind == "literal":
        value = expr.get("value")
        if isinstance(value, bool):
            return ScalarType.BOOL
        if isinstance(value, int) and not isinstance(value, bool):
            return ScalarType.INT
        if isinstance(value, float):
            return ScalarType.DECIMAL
        if isinstance(value, str):
            return ScalarType.STRING
    if kind == "ref" and str(expr.get("id", "")).startswith("state__"):
        target = calc_asts.get(str(expr["id"]))
        if target is not None:
            return _infer_output_type_from_state(target, calc_asts)
    if kind in {"and", "or", "not", "=", "!=", "<", "<=", ">", ">=", "selected"}:
        return ScalarType.BOOL
    if kind in {"+", "-", "*", "/"}:
        return ScalarType.DECIMAL
    if kind == "if":
        return _infer_value_type(expr["then"], calc_asts) or _infer_value_type(expr["else"], calc_asts)
    return None


def _resolve_assignment_refs(
    expr: dict[str, Any],
    variable_ids: set[str],
    predicate_ids: set[str],
    output_ids: set[str],
    *,
    symbol_types: dict[str, ScalarType],
    state_alias_map: dict[str, str],
) -> dict[str, Any] | Any:
    if expr.get("kind") == "literal":
        return expr["value"]
    return _resolve_refs(
        expr,
        variable_ids,
        predicate_ids,
        output_ids,
        symbol_types=symbol_types,
        state_alias_map=state_alias_map,
        allow_temporaries=False,
    )


def _resolve_refs(
    expr: dict[str, Any],
    variable_ids: set[str],
    predicate_ids: set[str],
    output_ids: set[str],
    *,
    symbol_types: dict[str, ScalarType],
    state_alias_map: dict[str, str],
    allow_temporaries: bool,
) -> dict[str, Any]:
    kind = expr.get("kind")
    if kind == "ref":
        identifier = str(expr["id"])
        if identifier in state_alias_map:
            identifier = state_alias_map[identifier]
        if identifier in variable_ids:
            return {"kind": "var", "id": identifier}
        if identifier in predicate_ids:
            return {"kind": "pred", "id": identifier}
        if identifier in output_ids:
            return {"kind": "output", "id": identifier}
        if allow_temporaries:
            return expr
        raise XLSFormImportError(f"unsupported XLSForm reference '{identifier}' during IR import")
    if kind in {"literal", "else"}:
        return expr
    if kind in {"and", "or"}:
        return {
            "kind": kind,
            "args": [
                _resolve_refs(
                    item,
                    variable_ids,
                    predicate_ids,
                    output_ids,
                    symbol_types=symbol_types,
                    state_alias_map=state_alias_map,
                    allow_temporaries=allow_temporaries,
                )
                for item in expr["args"]
            ],
        }
    if kind == "not":
        return {
            "kind": "not",
            "arg": _resolve_refs(
                expr["arg"],
                variable_ids,
                predicate_ids,
                output_ids,
                symbol_types=symbol_types,
                state_alias_map=state_alias_map,
                allow_temporaries=allow_temporaries,
            ),
        }
    if kind == "if":
        return {
            "kind": "if",
            "cond": _resolve_refs(expr["cond"], variable_ids, predicate_ids, output_ids, symbol_types=symbol_types, state_alias_map=state_alias_map, allow_temporaries=allow_temporaries),
            "then": _resolve_refs(expr["then"], variable_ids, predicate_ids, output_ids, symbol_types=symbol_types, state_alias_map=state_alias_map, allow_temporaries=allow_temporaries),
            "else": _resolve_refs(expr["else"], variable_ids, predicate_ids, output_ids, symbol_types=symbol_types, state_alias_map=state_alias_map, allow_temporaries=allow_temporaries),
        }
    if kind in {"=", "!=", "<", "<=", ">", ">=", "+", "-", "*", "/"}:
        left = _resolve_refs(expr["left"], variable_ids, predicate_ids, output_ids, symbol_types=symbol_types, state_alias_map=state_alias_map, allow_temporaries=allow_temporaries)
        right = _resolve_refs(expr["right"], variable_ids, predicate_ids, output_ids, symbol_types=symbol_types, state_alias_map=state_alias_map, allow_temporaries=allow_temporaries)
        normalized = _normalize_bool_string_compare(kind, left, right, symbol_types)
        if normalized is not None:
            return normalized
        return {
            "kind": kind,
            "left": left,
            "right": right,
        }
    if kind == "selected":
        return {
            "kind": "selected",
            "target": _resolve_refs(expr["target"], variable_ids, predicate_ids, output_ids, symbol_types=symbol_types, state_alias_map=state_alias_map, allow_temporaries=allow_temporaries),
            "choice": expr["choice"],
        }
    raise XLSFormImportError(f"unsupported expression kind '{kind}' during XLSForm import")


def _collect_var_refs(expr: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    kind = expr.get("kind")
    if kind == "ref" and str(expr.get("id", "")).startswith(("v_", "st_")):
        refs.add(str(expr["id"]))
    for key in ("arg", "left", "right", "cond", "then", "else", "target"):
        child = expr.get(key)
        if isinstance(child, dict):
            refs |= _collect_var_refs(child)
    for child in expr.get("args", []):
        if isinstance(child, dict):
            refs |= _collect_var_refs(child)
    return refs


def _row_provenance(source_id: str | None, row_number: int, location: str) -> ProvenanceRecord:
    return ProvenanceRecord(
        source_id=source_id or "xlsform_import",
        kind="xlsform_row",
        row=row_number,
        location=location,
    )


def _row_number(workbook: XLSFormWorkbook, row_name: str) -> int:
    return _row_number_by_name(workbook, row_name)


def _row_number_by_name(workbook: XLSFormWorkbook, row_name: str) -> int:
    for index, row in enumerate(workbook.survey):
        if row.name == row_name:
            return index + 2
    return 2


def _state_output_id(state_row_name: str) -> str:
    _, output_id, _ = state_row_name.split("__", 2)
    return output_id


def _symbol_type_map(
    *,
    variables: dict[str, VariableDef],
    predicate_ids: set[str],
    outputs: dict[str, OutputDef],
) -> dict[str, ScalarType]:
    mapping = {identifier: variable.type for identifier, variable in variables.items()}
    for identifier in predicate_ids:
        mapping[identifier] = ScalarType.BOOL
    for identifier, output in outputs.items():
        mapping[identifier] = output.type
    return mapping


def _normalize_bool_string_compare(
    operator: str,
    left: dict[str, Any],
    right: dict[str, Any],
    symbol_types: dict[str, ScalarType],
) -> dict[str, Any] | None:
    bool_literal = _bool_string_literal(right)
    left_ref = _ref_id_for_boolish_symbol(left, symbol_types)
    if operator in {"=", "!="} and bool_literal is not None and left_ref is not None:
        return _bool_compare_result(operator, left, bool_literal)
    bool_literal = _bool_string_literal(left)
    right_ref = _ref_id_for_boolish_symbol(right, symbol_types)
    if operator in {"=", "!="} and bool_literal is not None and right_ref is not None:
        return _bool_compare_result(operator, right, bool_literal)
    return None


def _bool_string_literal(expr: dict[str, Any]) -> bool | None:
    if expr.get("kind") != "literal" or not isinstance(expr.get("value"), str):
        return None
    lowered = str(expr["value"]).strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


def _ref_id_for_boolish_symbol(expr: dict[str, Any], symbol_types: dict[str, ScalarType]) -> str | None:
    if expr.get("kind") not in {"var", "pred", "output"}:
        return None
    identifier = str(expr.get("id"))
    return identifier if symbol_types.get(identifier) is ScalarType.BOOL else None


def _bool_compare_result(operator: str, ref_expr: dict[str, Any], literal_value: bool) -> dict[str, Any]:
    if operator == "=":
        return ref_expr if literal_value else {"kind": "not", "arg": ref_expr}
    return {"kind": "not", "arg": ref_expr} if literal_value else ref_expr
