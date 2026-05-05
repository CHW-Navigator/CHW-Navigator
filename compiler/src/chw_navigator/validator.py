from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .clinical_ir import ClinicalIRDocument, DecisionDef, Domain, HitPolicy, ScalarType


@dataclass(slots=True)
class ValidationError:
    path: str
    message: str


def validate_document(document: ClinicalIRDocument) -> list[ValidationError]:
    errors: list[ValidationError] = []

    _validate_metadata(document, errors)
    _validate_identity_consistency(document, errors)
    _validate_identifier_prefixes(document, errors)
    _validate_provenance(document, errors)
    _validate_current_subset(document, errors)
    _validate_domains(document, errors)
    _validate_predicates(document, errors)
    _validate_phrases(document, errors)
    _validate_decisions(document, errors)
    _validate_invariants(document, errors)
    _validate_phrase_bindings(document, errors)
    _validate_predicate_dependencies(document, errors)

    return errors


def _validate_current_subset(document: ClinicalIRDocument, errors: list[ValidationError]) -> None:
    for variable in document.variables.values():
        if variable.multivalue:
            errors.append(
                ValidationError(
                    f"variables.{variable.id}.multivalue",
                    "multivalue variables are not yet supported by the current interpreter and XLSForm backend",
                )
            )


def _validate_metadata(document: ClinicalIRDocument, errors: list[ValidationError]) -> None:
    if not document.metadata.sources:
        errors.append(ValidationError("metadata.sources", "metadata must include at least one source record"))


def _validate_identity_consistency(document: ClinicalIRDocument, errors: list[ValidationError]) -> None:
    _check_named_section("variables", document.variables, errors)
    _check_named_section("constants", document.constants, errors)
    _check_named_section("predicates", document.predicates, errors)
    _check_named_section("phrases", document.phrases, errors)
    _check_named_section("decisions", document.decisions, errors)
    _check_named_section("outputs", document.outputs, errors)
    _check_named_section("invariants", document.invariants, errors)

    for decision_id, decision in document.decisions.items():
        seen_rule_ids: set[str] = set()
        for index, rule in enumerate(decision.rules):
            if not rule.id:
                errors.append(ValidationError(f"decisions.{decision_id}.rules[{index}].id", "rule id cannot be empty"))
            elif rule.id in seen_rule_ids:
                errors.append(ValidationError(f"decisions.{decision_id}.rules[{index}].id", f"duplicate rule id '{rule.id}'"))
            seen_rule_ids.add(rule.id)


def _validate_identifier_prefixes(document: ClinicalIRDocument, errors: list[ValidationError]) -> None:
    _check_prefixes("variables", document.variables, {"v_", "st_"}, errors)
    _check_prefixes("constants", document.constants, {"c_"}, errors)
    _check_prefixes("predicates", document.predicates, {"p_"}, errors)
    _check_prefixes("phrases", document.phrases, {"m_"}, errors)
    _check_prefixes("decisions", document.decisions, {"d_"}, errors)
    _check_prefixes("outputs", document.outputs, {"o_"}, errors)
    _check_prefixes("invariants", document.invariants, {"i_"}, errors)

    for decision_id, decision in document.decisions.items():
        for index, rule in enumerate(decision.rules):
            if not rule.id.startswith("r"):
                errors.append(
                    ValidationError(
                        f"decisions.{decision_id}.rules[{index}].id",
                        "rule ids must start with 'r'",
                    )
                )


def _check_prefixes(
    section_name: str,
    items: dict[str, Any],
    prefixes: set[str],
    errors: list[ValidationError],
) -> None:
    allowed = "/".join(sorted(prefixes))
    label = {
        "variables": "variable",
        "constants": "constant",
        "predicates": "predicate",
        "decisions": "decision",
        "outputs": "output",
        "invariants": "invariant",
    }.get(section_name, section_name)
    for key in items:
        if not any(key.startswith(prefix) for prefix in prefixes):
            errors.append(
                ValidationError(
                    f"{section_name}.{key}.id",
                    f"{label} ids must use one of the following prefixes: {allowed}",
                )
            )


def _check_named_section(section_name: str, items: dict[str, Any], errors: list[ValidationError]) -> None:
    for key, item in items.items():
        if getattr(item, "id", key) != key:
            errors.append(
                ValidationError(
                    f"{section_name}.{key}.id",
                    f"section key '{key}' must match embedded id '{getattr(item, 'id', None)}'",
                )
            )


def _validate_provenance(document: ClinicalIRDocument, errors: list[ValidationError]) -> None:
    for section_name, items in (
        ("variables", document.variables),
        ("constants", document.constants),
        ("predicates", document.predicates),
        ("phrases", document.phrases),
        ("decisions", document.decisions),
        ("outputs", document.outputs),
        ("invariants", document.invariants),
    ):
        for key, item in items.items():
            if not getattr(item, "provenance", []):
                errors.append(ValidationError(f"{section_name}.{key}.provenance", "provenance is required"))

    for decision_id, decision in document.decisions.items():
        for index, rule in enumerate(decision.rules):
            if not rule.provenance:
                errors.append(
                    ValidationError(
                        f"decisions.{decision_id}.rules[{index}].provenance",
                        "provenance is required",
                    )
                )


def _validate_domains(document: ClinicalIRDocument, errors: list[ValidationError]) -> None:
    for variable in document.variables.values():
        _validate_domain(f"variables.{variable.id}.domain", variable.type, variable.domain, errors)

    for output_def in document.outputs.values():
        _validate_domain(f"outputs.{output_def.id}.domain", output_def.type, output_def.domain, errors)


def _validate_domain(
    path: str,
    scalar_type: ScalarType,
    domain: Domain | None,
    errors: list[ValidationError],
) -> None:
    if domain is None:
        if scalar_type is ScalarType.ENUM:
            errors.append(ValidationError(path, "enum types must define domain values"))
        return
    if domain.min is not None and domain.max is not None and domain.min > domain.max:
        errors.append(ValidationError(path, "domain min cannot be greater than max"))
    if domain.values is not None and not domain.values:
        errors.append(ValidationError(path, "domain values cannot be empty"))
    if scalar_type is ScalarType.ENUM and not domain.values:
        errors.append(ValidationError(path, "enum types must define non-empty domain values"))


def _validate_predicates(document: ClinicalIRDocument, errors: list[ValidationError]) -> None:
    for predicate in document.predicates.values():
        for identifier in predicate.inputs_used:
            if identifier not in document.variables:
                errors.append(
                    ValidationError(
                        f"predicates.{predicate.id}.inputs_used",
                        f"unknown variable reference '{identifier}'",
                    )
                )
        expr_type = _infer_expr_type(
            predicate.expression,
            document,
            f"predicates.{predicate.id}.expression",
            errors,
        )
        _expect_type(
            expected=ScalarType.BOOL,
            actual=expr_type,
            path=f"predicates.{predicate.id}.expression",
            errors=errors,
            context="predicate expression",
        )


def _validate_phrases(document: ClinicalIRDocument, errors: list[ValidationError]) -> None:
    for phrase in document.phrases.values():
        if not phrase.texts:
            errors.append(
                ValidationError(
                    f"phrases.{phrase.key}.texts",
                    "phrase must define at least one language text",
                )
            )
        for language, text in phrase.texts.items():
            if not language.strip():
                errors.append(
                    ValidationError(
                        f"phrases.{phrase.key}.texts",
                        "phrase language keys cannot be empty",
                    )
                )
            if not text.strip():
                errors.append(
                    ValidationError(
                        f"phrases.{phrase.key}.texts.{language}",
                        "phrase text cannot be empty",
                    )
                )
        if phrase.entity_id.startswith("o_"):
            continue
        if phrase.entity_id not in document.variables and phrase.entity_id not in document.predicates:
            errors.append(
                ValidationError(
                    f"phrases.{phrase.key}.entity_id",
                    f"phrase references unknown entity '{phrase.entity_id}'",
                )
            )


def _validate_decisions(document: ClinicalIRDocument, errors: list[ValidationError]) -> None:
    seen_rule_ids: set[str] = set()

    for decision in document.decisions.values():
        _validate_decision(decision, document, seen_rule_ids, errors)


def _validate_decision(
    decision: DecisionDef,
    document: ClinicalIRDocument,
    seen_rule_ids: set[str],
    errors: list[ValidationError],
) -> None:
    if decision.hit_policy is not HitPolicy.FIRST:
        errors.append(
            ValidationError(
                f"decisions.{decision.id}.hit_policy",
                f"unsupported hit policy '{decision.hit_policy}'",
            )
        )
    if not decision.rules:
        errors.append(ValidationError(f"decisions.{decision.id}.rules", "decision must include at least one rule"))
        return

    else_count = 0
    for index, rule in enumerate(decision.rules):
        if rule.id in seen_rule_ids:
            errors.append(ValidationError(f"decisions.{decision.id}.rules[{index}].id", f"duplicate rule id '{rule.id}'"))
        seen_rule_ids.add(rule.id)

        if _is_else(rule.when):
            else_count += 1
            if index != len(decision.rules) - 1:
                errors.append(
                    ValidationError(
                        f"decisions.{decision.id}.rules[{index}].when",
                        "else rule must be the final rule",
                    )
                )
        else:
            when_type = _infer_expr_type(
                rule.when,
                document,
                f"decisions.{decision.id}.rules[{index}].when",
                errors,
            )
            _expect_type(
                expected=ScalarType.BOOL,
                actual=when_type,
                path=f"decisions.{decision.id}.rules[{index}].when",
                errors=errors,
                context="rule condition",
            )

        if not rule.then:
            errors.append(
                ValidationError(
                    f"decisions.{decision.id}.rules[{index}].then",
                    "rule must assign at least one output",
                )
            )
        for output_name, raw_value in rule.then.items():
            if output_name not in document.outputs:
                errors.append(
                    ValidationError(
                        f"decisions.{decision.id}.rules[{index}].then",
                        f"unknown output reference '{output_name}'",
                    )
                )
                continue
            output_type = document.outputs[output_name].type
            actual_type = _infer_assignment_type(
                raw_value,
                document,
                f"decisions.{decision.id}.rules[{index}].then.{output_name}",
                errors,
            )
            _expect_type(
                expected=output_type,
                actual=actual_type,
                path=f"decisions.{decision.id}.rules[{index}].then.{output_name}",
                errors=errors,
                context="output assignment",
            )

    if else_count != 1:
        errors.append(ValidationError(f"decisions.{decision.id}.rules", "decision must include exactly one else rule"))


def _validate_invariants(document: ClinicalIRDocument, errors: list[ValidationError]) -> None:
    for invariant in document.invariants.values():
        expr_type = _infer_expr_type(
            invariant.expression,
            document,
            f"invariants.{invariant.id}.expression",
            errors,
        )
        _expect_type(
            expected=ScalarType.BOOL,
            actual=expr_type,
            path=f"invariants.{invariant.id}.expression",
            errors=errors,
            context="invariant expression",
        )


def _validate_phrase_bindings(document: ClinicalIRDocument, errors: list[ValidationError]) -> None:
    for output_name, binding in document.phrase_bindings.items():
        if output_name not in document.outputs:
            errors.append(
                ValidationError(
                    f"phrase_bindings.{output_name}",
                    f"phrase binding references unknown output '{output_name}'",
                )
            )
        elif not any(binding.get(key) for key in ("message_key", "guidance_key")):
            errors.append(
                ValidationError(
                    f"phrase_bindings.{output_name}",
                    "phrase binding must include a non-empty message_key or guidance_key",
                )
            )


def _validate_predicate_dependencies(document: ClinicalIRDocument, errors: list[ValidationError]) -> None:
    graph: dict[str, set[str]] = {}
    for predicate in document.predicates.values():
        graph[predicate.id] = _collect_refs(predicate.expression, {"pred"})

    temp_mark: set[str] = set()
    perm_mark: set[str] = set()

    def visit(node: str) -> None:
        if node in perm_mark:
            return
        if node in temp_mark:
            errors.append(ValidationError(f"predicates.{node}.expression", "cyclic predicate dependency detected"))
            return
        temp_mark.add(node)
        for child in graph.get(node, set()):
            if child in graph:
                visit(child)
        temp_mark.remove(node)
        perm_mark.add(node)

    for node in graph:
        visit(node)


def _infer_assignment_type(
    value: Any,
    document: ClinicalIRDocument,
    path: str,
    errors: list[ValidationError],
) -> ScalarType | None:
    if isinstance(value, dict) and "kind" in value:
        return _infer_expr_type(value, document, path, errors)
    return _infer_python_value_type(value)


def _infer_expr_type(
    expr: dict[str, Any],
    document: ClinicalIRDocument,
    path: str,
    errors: list[ValidationError],
) -> ScalarType | None:
    kind = expr.get("kind")
    if not kind:
        errors.append(ValidationError(path, "expression must include a kind"))
        return None

    if kind == "literal":
        if "type" in expr:
            try:
                return ScalarType(expr["type"])
            except ValueError:
                errors.append(ValidationError(path, f"unsupported literal type '{expr['type']}'"))
                return None
        return _infer_python_value_type(expr.get("value"))
    if kind == "else":
        return ScalarType.BOOL
    if kind == "var":
        identifier = expr.get("id")
        if identifier not in document.variables:
            errors.append(ValidationError(path, f"unknown variable reference '{identifier}'"))
            return None
        return document.variables[identifier].type
    if kind == "const":
        identifier = expr.get("id")
        if identifier not in document.constants:
            errors.append(ValidationError(path, f"unknown constant reference '{identifier}'"))
            return None
        return document.constants[identifier].type
    if kind == "pred":
        identifier = expr.get("id")
        if identifier not in document.predicates:
            errors.append(ValidationError(path, f"unknown predicate reference '{identifier}'"))
            return None
        return ScalarType.BOOL
    if kind == "output":
        identifier = expr.get("id")
        if identifier not in document.outputs:
            errors.append(ValidationError(path, f"unknown output reference '{identifier}'"))
            return None
        return document.outputs[identifier].type

    if kind in {"and", "or", "exactly_one"}:
        args = expr.get("args")
        if not isinstance(args, list) or not args:
            errors.append(ValidationError(path, f"'{kind}' requires a non-empty args list"))
            return None
        for index, arg in enumerate(args):
            arg_type = _infer_expr_type(arg, document, f"{path}.args[{index}]", errors)
            _expect_type(ScalarType.BOOL, arg_type, f"{path}.args[{index}]", errors, f"'{kind}' argument")
        return ScalarType.BOOL

    if kind == "not":
        arg = expr.get("arg")
        if not isinstance(arg, dict):
            errors.append(ValidationError(path, "'not' requires an arg expression"))
            return None
        arg_type = _infer_expr_type(arg, document, f"{path}.arg", errors)
        _expect_type(ScalarType.BOOL, arg_type, f"{path}.arg", errors, "'not' argument")
        return ScalarType.BOOL

    if kind == "if":
        cond = expr.get("cond")
        then_expr = expr.get("then")
        else_expr = expr.get("else")
        if not all(isinstance(item, dict) for item in [cond, then_expr, else_expr]):
            errors.append(ValidationError(path, "'if' requires cond, then, and else expressions"))
            return None
        cond_type = _infer_expr_type(cond, document, f"{path}.cond", errors)
        _expect_type(ScalarType.BOOL, cond_type, f"{path}.cond", errors, "'if' condition")
        then_type = _infer_expr_type(then_expr, document, f"{path}.then", errors)
        else_type = _infer_expr_type(else_expr, document, f"{path}.else", errors)
        if then_type is None or else_type is None:
            return None
        if not _types_compatible(then_type, else_type):
            errors.append(
                ValidationError(
                    path,
                    f"'if' branches must have compatible types, got '{then_type}' and '{else_type}'",
                )
            )
            return None
        return then_type

    if kind in {"=", "!="}:
        left_type, right_type = _infer_binary_operand_types(expr, document, path, errors)
        if left_type is None or right_type is None:
            return ScalarType.BOOL
        if not _types_compatible(left_type, right_type):
            errors.append(
                ValidationError(path, f"comparison operands must have compatible types, got '{left_type}' and '{right_type}'")
            )
        return ScalarType.BOOL

    if kind in {"<", "<=", ">", ">="}:
        left_type, right_type = _infer_binary_operand_types(expr, document, path, errors)
        if left_type is not None and not _is_numeric(left_type):
            errors.append(ValidationError(f"{path}.left", f"operator '{kind}' requires numeric operands"))
        if right_type is not None and not _is_numeric(right_type):
            errors.append(ValidationError(f"{path}.right", f"operator '{kind}' requires numeric operands"))
        return ScalarType.BOOL

    if kind in {"+", "-", "*", "/"}:
        left_type, right_type = _infer_binary_operand_types(expr, document, path, errors)
        if left_type is not None and not _is_numeric(left_type):
            errors.append(ValidationError(f"{path}.left", f"operator '{kind}' requires numeric operands"))
        if right_type is not None and not _is_numeric(right_type):
            errors.append(ValidationError(f"{path}.right", f"operator '{kind}' requires numeric operands"))
        if left_type is ScalarType.DECIMAL or right_type is ScalarType.DECIMAL:
            return ScalarType.DECIMAL
        return ScalarType.INT if left_type is not None and right_type is not None else None

    if kind == "selected":
        target = expr.get("target")
        choice = expr.get("choice")
        if not isinstance(target, dict):
            errors.append(ValidationError(path, "'selected' requires a target expression"))
            return None
        if not isinstance(choice, str) or not choice:
            errors.append(ValidationError(path, "'selected' requires a non-empty choice string"))
            return None
        target_type = _infer_expr_type(target, document, f"{path}.target", errors)
        if target_type not in {ScalarType.STRING, ScalarType.STRING_KEY, ScalarType.ENUM}:
            errors.append(
                ValidationError(
                    f"{path}.target",
                    f"'selected' target must be string-like, got '{target_type}'",
                )
            )
        if target.get("kind") == "var":
            variable_id = target.get("id")
            variable = document.variables.get(variable_id)
            if variable is not None and not variable.multivalue:
                errors.append(
                    ValidationError(
                        f"{path}.target",
                        f"'selected' target variable '{variable_id}' must be declared multivalue in the current subset",
                    )
                )
        return ScalarType.BOOL

    errors.append(ValidationError(path, f"unsupported expression kind '{kind}'"))
    return None


def _infer_binary_operand_types(
    expr: dict[str, Any],
    document: ClinicalIRDocument,
    path: str,
    errors: list[ValidationError],
) -> tuple[ScalarType | None, ScalarType | None]:
    left = expr.get("left")
    right = expr.get("right")
    if not isinstance(left, dict) or not isinstance(right, dict):
        errors.append(ValidationError(path, f"'{expr.get('kind')}' requires left and right expressions"))
        return None, None
    left_type = _infer_expr_type(left, document, f"{path}.left", errors)
    right_type = _infer_expr_type(right, document, f"{path}.right", errors)
    return left_type, right_type


def _infer_python_value_type(value: Any) -> ScalarType | None:
    if isinstance(value, bool):
        return ScalarType.BOOL
    if isinstance(value, int) and not isinstance(value, bool):
        return ScalarType.INT
    if isinstance(value, float):
        return ScalarType.DECIMAL
    if isinstance(value, str):
        return ScalarType.STRING
    if value is None:
        return None
    return None


def _expect_type(
    expected: ScalarType,
    actual: ScalarType | None,
    path: str,
    errors: list[ValidationError],
    context: str,
) -> None:
    if actual is None:
        return
    if not _types_compatible(expected, actual):
        errors.append(
            ValidationError(
                path,
                f"{context} must have type '{expected}', got '{actual}'",
            )
        )


def _types_compatible(left: ScalarType, right: ScalarType) -> bool:
    if left == right:
        return True
    string_like = {ScalarType.STRING, ScalarType.STRING_KEY}
    if left in string_like and right in string_like:
        return True
    numeric = {ScalarType.INT, ScalarType.DECIMAL}
    return left in numeric and right in numeric


def _is_numeric(scalar_type: ScalarType) -> bool:
    return scalar_type in {ScalarType.INT, ScalarType.DECIMAL}


def _collect_refs(expr: dict[str, Any], kinds: set[str]) -> set[str]:
    kind = expr.get("kind")
    if kind in kinds and "id" in expr:
        return {str(expr["id"])}
    if kind in {"literal", "else"}:
        return set()
    if kind in {"var", "const", "pred", "output"}:
        return set()
    if kind in {"and", "or", "exactly_one"}:
        refs: set[str] = set()
        for arg in expr.get("args", []):
            refs |= _collect_refs(arg, kinds)
        return refs
    if kind == "not":
        arg = expr.get("arg", {})
        return _collect_refs(arg, kinds) if isinstance(arg, dict) else set()
    if kind == "if":
        refs: set[str] = set()
        for key in ("cond", "then", "else"):
            value = expr.get(key, {})
            if isinstance(value, dict):
                refs |= _collect_refs(value, kinds)
        return refs
    if kind in {"=", "!=", "<", "<=", ">", ">=", "+", "-", "*", "/"}:
        refs: set[str] = set()
        left = expr.get("left", {})
        right = expr.get("right", {})
        if isinstance(left, dict):
            refs |= _collect_refs(left, kinds)
        if isinstance(right, dict):
            refs |= _collect_refs(right, kinds)
        return refs
    if kind == "selected":
        target = expr.get("target", {})
        return _collect_refs(target, kinds) if isinstance(target, dict) else set()
    return set()


def _is_else(expr: dict[str, Any]) -> bool:
    return expr.get("kind") == "else"
