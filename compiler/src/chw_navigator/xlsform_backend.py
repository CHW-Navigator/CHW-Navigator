from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .clinical_ir import ClinicalIRDocument, MissingnessPolicy, ScalarType
from .form_ir import ChoiceRow, SurveyRow, XLSFormWorkbook


class XLSFormBuildError(Exception):
    """Raised when a Clinical IR document cannot be lowered to the supported XLSForm subset."""


@dataclass(slots=True)
class BuiltXLSForm:
    workbook: XLSFormWorkbook
    rule_row_names: dict[str, str] = field(default_factory=dict)
    predicate_row_names: dict[str, str] = field(default_factory=dict)
    output_row_names: dict[str, str] = field(default_factory=dict)
    row_sources: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def build_xlsform(document: ClinicalIRDocument) -> BuiltXLSForm:
    workbook = XLSFormWorkbook(
        title=document.metadata.guideline_id,
        form_id=document.metadata.guideline_id,
    )
    built = BuiltXLSForm(workbook=workbook)
    added_choice_lists: set[str] = set()

    if any(var.type is ScalarType.BOOL for var in document.variables.values()):
        _ensure_yes_no_choices(workbook, added_choice_lists)

    for variable in document.variables.values():
        workbook.survey.append(_variable_row(variable, document, workbook, added_choice_lists))
        built.row_sources[variable.id] = _provenance_dicts(variable.provenance)

    for predicate_id, predicate in document.predicates.items():
        row_name = predicate_id
        built.predicate_row_names[predicate_id] = row_name
        predicate_expr = _compile_predicate(predicate, document)
        workbook.survey.append(
            SurveyRow(
                type="calculate",
                name=row_name,
                calculation=predicate_expr,
                role="predicate",
            )
        )
        built.row_sources[row_name] = _provenance_dicts(predicate.provenance)

    current_output_rows: dict[str, str] = {}

    for decision in document.decisions.values():
        prior_rule_row_names: list[str] = []
        for rule in decision.rules:
            row_name = f"rh_{rule.id}"
            built.rule_row_names[rule.id] = row_name
            prior_false_terms = [f"not(${{{name}}})" for name in prior_rule_row_names]
            if rule.when.get("kind") == "else":
                condition = " and ".join(prior_false_terms) if prior_false_terms else "true()"
            else:
                terms = [_compile_expr(rule.when, document, current_output_rows)] + prior_false_terms
                condition = " and ".join(f"({term})" for term in terms if term)
            workbook.survey.append(
                SurveyRow(
                    type="calculate",
                    name=row_name,
                    calculation=f"if({condition}, true(), false())",
                    role="rule_hit",
                )
            )
            built.row_sources[row_name] = _merge_provenance(decision.provenance, rule.provenance)
            prior_rule_row_names.append(row_name)

        decision_outputs = sorted(
            {
                output_id
                for rule in decision.rules
                for output_id in rule.then
            }
        )
        prior_output_rows = dict(current_output_rows)
        for output_id in decision_outputs:
            output_def = document.outputs[output_id]
            state_row_name = f"state__{output_id}__{decision.id}"
            workbook.survey.append(
                SurveyRow(
                    type="calculate",
                    name=state_row_name,
                    calculation=_compile_output_state(
                        output_id,
                        output_def.type,
                        document,
                        decision.id,
                        built.rule_row_names,
                        prior_output_rows,
                    ),
                    role="output_state",
                )
            )
            assigning_rule_provenance = [
                rule.provenance
                for rule in decision.rules
                if output_id in rule.then
            ]
            built.row_sources[state_row_name] = _merge_provenance(
                output_def.provenance,
                decision.provenance,
                *assigning_rule_provenance,
            )
            current_output_rows[output_id] = state_row_name

    for output_id, output_def in document.outputs.items():
        built.output_row_names[output_id] = output_id
        state_row_name = current_output_rows.get(output_id)
        final_calculation = f"${{{state_row_name}}}" if state_row_name else _default_literal(output_def.type)
        workbook.survey.append(
            SurveyRow(
                type="calculate",
                name=output_id,
                calculation=final_calculation,
                role="output",
            )
        )
        assigning_rule_provenance = [
            rule.provenance
            for decision in document.decisions.values()
            for rule in decision.rules
            if output_id in rule.then
        ]
        built.row_sources[output_id] = _merge_provenance(output_def.provenance, *assigning_rule_provenance)

    for output_id, label, role in _output_phrase_rows(document):
        for row_name, resolved_label, resolved_role in _phrase_rows(output_id, label, role):
            workbook.survey.append(
                SurveyRow(
                    type="note",
                    name=row_name,
                    label=resolved_label,
                    relevant=f"${{{output_id}}}",
                    role=resolved_role,
                )
            )
            built.row_sources[row_name] = _provenance_dicts(document.outputs[output_id].provenance)

    return built


def write_xlsform_csvs(built: BuiltXLSForm, output_dir: str) -> tuple[str, str, str]:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    survey_path = path / "survey.csv"
    choices_path = path / "choices.csv"
    source_map_path = path / "source-map.json"

    survey_lines = [",".join(built.workbook.survey_headers())]
    for row in built.workbook.survey:
        survey_lines.append(
            ",".join(
                _csv_cell(value)
                for value in [
                    row.type,
                    row.name,
                    row.label,
                    row.relevant,
                    row.calculation,
                    row.required,
                    row.constraint,
                    row.appearance,
                ]
            )
        )

    choice_lines = [",".join(built.workbook.choice_headers())]
    for row in built.workbook.choices:
        choice_lines.append(",".join(_csv_cell(value) for value in [row.list_name, row.name, row.label]))

    survey_path.write_text("\n".join(survey_lines) + "\n", encoding="utf-8")
    choices_path.write_text("\n".join(choice_lines) + "\n", encoding="utf-8")
    source_map_path.write_text(
        _render_json(
            {
                "form_id": built.workbook.form_id,
                "title": built.workbook.title,
                "row_sources": built.row_sources,
            }
        ),
        encoding="utf-8",
    )
    return str(survey_path), str(choices_path), str(source_map_path)


def _variable_row(variable, document: ClinicalIRDocument, workbook: XLSFormWorkbook, added_choice_lists: set[str]) -> SurveyRow:
    label = _phrase_text_for_entity(document, variable.id, "label", fallback=variable.id)
    if variable.type is ScalarType.INT:
        return SurveyRow(type="integer", name=variable.id, label=label, required=_required_cell(variable))
    if variable.type is ScalarType.DECIMAL:
        return SurveyRow(type="decimal", name=variable.id, label=label, required=_required_cell(variable))
    if variable.type in {ScalarType.STRING, ScalarType.STRING_KEY}:
        return SurveyRow(type="text", name=variable.id, label=label, required=_required_cell(variable))
    if variable.type is ScalarType.BOOL:
        return SurveyRow(
            type="select_one yes_no",
            name=variable.id,
            label=label,
            required=_required_cell(variable),
        )
    if variable.type is ScalarType.ENUM:
        if not variable.domain or not variable.domain.values:
            raise XLSFormBuildError(f"enum variable '{variable.id}' is missing domain values")
        list_name = f"list_{variable.id}"
        if list_name not in added_choice_lists:
            for value in variable.domain.values:
                workbook.choices.append(ChoiceRow(list_name=list_name, name=value, label=value))
            added_choice_lists.add(list_name)
        return SurveyRow(
            type=f"select_one {list_name}",
            name=variable.id,
            label=label,
            required=_required_cell(variable),
        )
    raise XLSFormBuildError(f"unsupported variable type '{variable.type}'")


def _compile_output_state(
    output_id: str,
    output_type: ScalarType,
    document: ClinicalIRDocument,
    decision_id: str,
    rule_row_names: dict[str, str],
    current_output_rows: dict[str, str],
) -> str:
    previous_row_name = current_output_rows.get(output_id)
    previous_value = f"${{{previous_row_name}}}" if previous_row_name else _default_literal(output_type)
    assignments: list[tuple[str, str]] = []
    for rule in document.decisions[decision_id].rules:
        if output_id in rule.then:
            assignments.append(
                (
                    rule_row_names[rule.id],
                    _compile_assignment_value(rule.then[output_id], output_type, document, current_output_rows),
                )
            )

    result = previous_value
    for row_name, value in reversed(assignments):
        result = f"if(${{{row_name}}}, {value}, {result})"
    return result


def _compile_predicate(predicate, document: ClinicalIRDocument) -> str:
    expression = _compile_expr(predicate.expression, document, {})
    if predicate.missingness_policy is MissingnessPolicy.TREAT_MISSING_AS_FALSE:
        return f"if({expression}, true(), false())"
    return expression


def compile_xlsform_expression(
    expr: dict[str, object],
    document: ClinicalIRDocument,
    *,
    output_rows: dict[str, str] | None = None,
) -> str:
    """Compile one validated Clinical IR expression for a backend-owned XLSForm row."""

    return _compile_expr(expr, document, output_rows)


def _phrase_rows(output_id: str, label: str, role: str) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    row_name = f"note_{output_id}" if role == "message" else f"guidance_{output_id}"
    rows.append((row_name, label, role))
    return rows


def _compile_expr(
    expr: dict[str, object],
    document: ClinicalIRDocument,
    output_rows: dict[str, str] | None = None,
) -> str:
    kind = expr["kind"]
    if kind == "literal":
        return _compile_untyped_literal(expr.get("value"))
    if kind == "var":
        variable = document.variables[str(expr["id"])]
        if variable.type is ScalarType.BOOL:
            return f"(${{{expr['id']}}} = 'true')"
        return f"${{{expr['id']}}}"
    if kind == "pred" or kind == "output":
        if kind == "pred":
            return f"${{{expr['id']}}}"
        output_id = str(expr["id"])
        if output_rows is None:
            raise XLSFormBuildError(
                f"unsupported output reference '{output_id}' outside sequential decision lowering"
            )
        row_name = output_rows.get(output_id)
        if row_name is not None:
            return f"${{{row_name}}}"
        return _default_literal(document.outputs[output_id].type)
    if kind == "const":
        const_value = document.constants[str(expr["id"])].value
        return _compile_untyped_literal(const_value)
    if kind == "call":
        return _compile_helper_call(expr, document, output_rows)
    if kind == "not":
        return f"not({_compile_expr(expr['arg'], document, output_rows)})"
    if kind == "and":
        return "(" + " and ".join(_compile_expr(arg, document, output_rows) for arg in expr["args"]) + ")"
    if kind == "or":
        return "(" + " or ".join(_compile_expr(arg, document, output_rows) for arg in expr["args"]) + ")"
    if kind == "if":
        return "if({cond}, {then}, {else_})".format(
            cond=_compile_expr(expr["cond"], document, output_rows),
            then=_compile_expr(expr["then"], document, output_rows),
            else_=_compile_expr(expr["else"], document, output_rows),
        )
    if kind in {"=", "!=", "<", "<=", ">", ">=", "+", "-", "*", "/"}:
        return "({left} {op} {right})".format(
            left=_compile_expr(expr["left"], document, output_rows),
            op="=" if kind == "=" else kind,
            right=_compile_expr(expr["right"], document, output_rows),
        )
    if kind == "selected":
        target = _compile_expr(expr["target"], document, output_rows)
        choice = _compile_untyped_literal(expr["choice"])
        return f"selected({target}, {choice})"
    raise XLSFormBuildError(f"unsupported expression kind '{kind}' for XLSForm lowering")


def _compile_helper_call(
    expr: dict[str, object],
    document: ClinicalIRDocument,
    output_rows: dict[str, str] | None,
) -> str:
    fn = str(expr["fn"])
    args = list(expr.get("args", []))
    if fn == "is_missing":
        if len(args) != 1:
            raise XLSFormBuildError("is_missing requires exactly one argument")
        target = _compile_expr(args[0], document, output_rows)
        return f"({target} = '')"
    if fn == "date_diff_days":
        if len(args) != 2:
            raise XLSFormBuildError("date_diff_days requires exactly two arguments")
        left = _compile_expr(args[0], document, output_rows)
        right = _compile_expr(args[1], document, output_rows)
        missing_guard = f"(({left} = '') or ({right} = ''))"
        return f"if({missing_guard}, '', ({left} - {right}))"
    if fn == "age_months_from_date":
        if len(args) != 2:
            raise XLSFormBuildError("age_months_from_date requires exactly two arguments")
        left = _compile_expr(args[0], document, output_rows)
        right = _compile_expr(args[1], document, output_rows)
        missing_guard = f"(({left} = '') or ({right} = ''))"
        return f"if({missing_guard}, '', floor((({left} - {right}) / 30)))"
    if fn == "floor":
        if len(args) != 1:
            raise XLSFormBuildError("floor requires exactly one argument")
        target = _compile_expr(args[0], document, output_rows)
        return f"floor({target})"
    raise XLSFormBuildError(f"unsupported helper function '{fn}' for XLSForm lowering")


def _compile_assignment_value(
    value: object,
    output_type: ScalarType,
    document: ClinicalIRDocument,
    output_rows: dict[str, str],
) -> str:
    if isinstance(value, dict) and "kind" in value:
        return _compile_expr(value, document, output_rows)
    return _compile_literal(value, output_type)


def _compile_literal(value: object, scalar_type: ScalarType) -> str:
    if scalar_type is ScalarType.BOOL:
        return "true()" if bool(value) else "false()"
    return _compile_untyped_literal(value)


def _compile_untyped_literal(value: object) -> str:
    if isinstance(value, bool):
        return "true()" if value else "false()"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "''"
    return "'" + str(value).replace("'", "\\'") + "'"


def _default_literal(output_type: ScalarType) -> str:
    if output_type is ScalarType.BOOL:
        return "false()"
    if output_type in {ScalarType.INT, ScalarType.DECIMAL}:
        return "0"
    return "''"


def _required_cell(variable) -> str:
    return "true()" if not variable.allowed_missingness else ""


def _ensure_yes_no_choices(workbook: XLSFormWorkbook, added_choice_lists: set[str]) -> None:
    if "yes_no" in added_choice_lists:
        return
    workbook.choices.extend(
        [
            ChoiceRow(list_name="yes_no", name="true", label="Yes"),
            ChoiceRow(list_name="yes_no", name="false", label="No"),
        ]
    )
    added_choice_lists.add("yes_no")


def _output_phrase_rows(document: ClinicalIRDocument) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for phrase in document.phrases.values():
        if phrase.entity_id not in document.outputs:
            continue
        if phrase.role.value not in {"message", "guidance"}:
            continue
        marker = (phrase.entity_id, phrase.role.value)
        if marker in seen:
            continue
        rows.append((phrase.entity_id, _preferred_phrase_text(phrase.texts, fallback=phrase.key), phrase.role.value))
        seen.add(marker)
    for output_id, binding in document.phrase_bindings.items():
        if output_id not in document.outputs:
            continue
        for role, field_name in (("message", "message_key"), ("guidance", "guidance_key")):
            key = binding.get(field_name, "")
            if not key or (output_id, role) in seen:
                continue
            phrase = document.phrases.get(key)
            label = _preferred_phrase_text(phrase.texts, fallback=key) if phrase is not None else key
            rows.append((output_id, label, role))
            seen.add((output_id, role))
    return rows


def _phrase_text_for_entity(
    document: ClinicalIRDocument,
    entity_id: str,
    role: str,
    fallback: str,
) -> str:
    for phrase in document.phrases.values():
        if phrase.entity_id == entity_id and phrase.role.value == role:
            return _preferred_phrase_text(phrase.texts, fallback=fallback)
    return fallback


def _preferred_phrase_text(texts: dict[str, str], fallback: str) -> str:
    for language in ("en", "eng", "default"):
        text = texts.get(language)
        if text:
            return text
    for text in texts.values():
        if text:
            return text
    return fallback


def _csv_cell(value: str) -> str:
    escaped = value.replace('"', '""')
    return f'"{escaped}"'


def _merge_provenance(*record_lists) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for records in record_lists:
        for record in records:
            rendered = record.to_dict()
            key = repr(sorted(rendered.items()))
            if key not in seen:
                seen.add(key)
                merged.append(rendered)
    return merged


def _provenance_dicts(records) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


def _render_json(data: dict[str, Any]) -> str:
    import json

    return json.dumps(data, indent=2, sort_keys=True) + "\n"
