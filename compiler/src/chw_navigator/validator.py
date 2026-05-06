from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .clinical_ir import ClinicalIRDocument, DecisionDef, HitPolicy, ScalarType
from .expr_tools import collect_refs, is_else_expr


@dataclass(slots=True)
class ValidationError:
    path: str
    message: str


def validate_document(document: ClinicalIRDocument) -> list[ValidationError]:
    """Run semantic and runtime-subset validation on a Clinical IR document.

    Schema/local contract checks now happen earlier in Pydantic. This validator
    stays focused on the checks that still need the full dataclass document:
    expression typing, decision semantics, phrase bindings, and dependency logic.
    """

    errors: list[ValidationError] = []

    _validate_current_subset(document, errors)
    _validate_variables(document, errors)
    _validate_predicates(document, errors)
    _validate_actions(document, errors)
    _validate_decisions(document, errors)
    _validate_decision_dependencies(document, errors)
    _validate_invariants(document, errors)
    _validate_phrase_bindings(document, errors)
    _validate_predicate_dependencies(document, errors)

    return errors


def _validate_current_subset(document: ClinicalIRDocument, errors: list[ValidationError]) -> None:
    """Check limitations of the current evaluator/XLSForm/Z3 subset."""

    for variable in document.variables.values():
        if variable.multivalue:
            errors.append(
                ValidationError(
                    f"variables.{variable.id}.multivalue",
                    "multivalue variables are not yet supported by the current interpreter and XLSForm backend",
                )
            )


def _validate_variables(document: ClinicalIRDocument, errors: list[ValidationError]) -> None:
    """Check history-binding references and basic variable-level coherence."""

    for variable in document.variables.values():
        binding = variable.history_binding
        if binding is None:
            continue
        if binding.recorded_at_var is not None and binding.recorded_at_var not in document.variables:
            errors.append(
                ValidationError(
                    f"variables.{variable.id}.history_binding.recorded_at_var",
                    f"unknown variable reference '{binding.recorded_at_var}'",
                )
            )
        if (
            binding.must_collect_fresh_when is not None
            and binding.must_collect_fresh_when.get("kind") == "output"
        ):
            errors.append(
                ValidationError(
                    f"variables.{variable.id}.history_binding.must_collect_fresh_when",
                    "history freshness conditions must not reference outputs directly",
                )
            )


def _validate_predicates(document: ClinicalIRDocument, errors: list[ValidationError]) -> None:
    """Check predicate input references and expression typing."""

    for predicate in document.predicates.values():
        for identifier in predicate.inputs_used:
            if identifier not in document.variables:
                errors.append(
                    ValidationError(
                        f"predicates.{predicate.id}.inputs_used",
                        f"unknown variable reference '{identifier}'",
                    )
                )
        output_refs = collect_refs(predicate.expression, {"output"})
        for output_id in sorted(output_refs):
            errors.append(
                ValidationError(
                    f"predicates.{predicate.id}.expression",
                    f"predicate must not reference output '{output_id}'",
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


def _validate_actions(document: ClinicalIRDocument, errors: list[ValidationError]) -> None:
    """Check action references without yet executing action semantics."""

    for action in document.actions.values():
        for output_name in action.outputs:
            if output_name not in document.variables and output_name not in document.outputs:
                errors.append(
                    ValidationError(
                        f"actions.{action.id}.outputs",
                        f"unknown output target '{output_name}'",
                    )
                )

        if action.when is not None:
            _infer_expr_type(action.when, document, f"actions.{action.id}.when", errors)

        if action.kind == "read_history":
            for output_name in action.outputs:
                if output_name in document.variables and not _is_history_id(output_name):
                    errors.append(
                        ValidationError(
                            f"actions.{action.id}.outputs",
                            "read_history outputs must target legacy h_ ids or variables with the _h suffix",
                        )
                    )
            for index, mapping in enumerate(action.mappings):
                if mapping.target_var not in document.variables:
                    errors.append(
                        ValidationError(
                            f"actions.{action.id}.mappings[{index}].target_var",
                            f"unknown variable reference '{mapping.target_var}'",
                        )
                    )
                if (
                    mapping.recorded_at_target_var is not None
                    and mapping.recorded_at_target_var not in document.variables
                ):
                    errors.append(
                        ValidationError(
                            f"actions.{action.id}.mappings[{index}].recorded_at_target_var",
                            f"unknown variable reference '{mapping.recorded_at_target_var}'",
                        )
                    )

        if action.kind == "compute" and action.expression is not None:
            _infer_expr_type(action.expression, document, f"actions.{action.id}.expression", errors)


def _validate_decisions(document: ClinicalIRDocument, errors: list[ValidationError]) -> None:
    """Check rule structure, output assignments, and ELSE semantics."""

    seen_rule_ids: set[str] = set()

    for decision in document.decisions.values():
        _validate_decision(decision, document, seen_rule_ids, errors)


def _validate_decision_dependencies(document: ClinicalIRDocument, errors: list[ValidationError]) -> None:
    """Check staged decision references point backward and resolve cleanly."""

    output_producers: dict[str, str] = {}
    for decision in document.decisions.values():
        for rule in decision.rules:
            for output_id in rule.then:
                output_producers.setdefault(output_id, decision.id)

    for decision in document.decisions.values():
        for dependency in decision.depends_on:
            if dependency not in document.decisions:
                errors.append(
                    ValidationError(
                        f"decisions.{decision.id}.depends_on",
                        f"unknown decision reference '{dependency}'",
                    )
                )
                continue
            prior = document.decisions[dependency]
            if decision.stage is not None and prior.stage is not None and prior.stage >= decision.stage:
                errors.append(
                    ValidationError(
                        f"decisions.{decision.id}.depends_on",
                        f"decision '{dependency}' must have a lower stage than '{decision.id}'",
                    )
                )

        for item in decision.inputs_used:
            if item.startswith("o_"):
                producer = output_producers.get(item)
                if producer is None:
                    errors.append(
                        ValidationError(
                            f"decisions.{decision.id}.inputs_used",
                            f"output input '{item}' is not produced by any decision rule",
                        )
                    )
                    continue
                if producer == decision.id:
                    errors.append(
                        ValidationError(
                            f"decisions.{decision.id}.inputs_used",
                            f"decision must not depend on its own output '{item}'",
                        )
                    )
                prior = document.decisions.get(producer)
                if decision.stage is not None and prior is not None and prior.stage is not None and prior.stage >= decision.stage:
                    errors.append(
                        ValidationError(
                            f"decisions.{decision.id}.inputs_used",
                            f"output input '{item}' must come from a lower-stage decision",
                        )
                    )


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

        if is_else_expr(rule.when):
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
    """Check invariant expressions type-check to booleans."""

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
    """Check phrase bindings only for runtime-required output references."""

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
    """Check predicate dependency graph is acyclic."""

    graph: dict[str, set[str]] = {}
    for predicate in document.predicates.values():
        graph[predicate.id] = collect_refs(predicate.expression, {"pred"})

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
    if kind == "call":
        fn = expr.get("fn")
        args = expr.get("args")
        if not isinstance(fn, str) or not fn:
            errors.append(ValidationError(path, "call expressions require fn"))
            return None
        if not isinstance(args, list):
            errors.append(ValidationError(path, "call expressions require args"))
            return None
        for index, arg in enumerate(args):
            if isinstance(arg, dict):
                _infer_expr_type(arg, document, f"{path}.args[{index}]", errors)
            else:
                errors.append(ValidationError(f"{path}.args[{index}]", "call arguments must be expressions"))
        if fn == "is_missing":
            if len(args) != 1:
                errors.append(ValidationError(path, "is_missing expects exactly one argument"))
            return ScalarType.BOOL
        if fn == "floor":
            if len(args) != 1:
                errors.append(ValidationError(path, "floor expects exactly one argument"))
                return None
            arg_type = _infer_expr_type(args[0], document, f"{path}.args[0]", errors)
            if arg_type is not None and not _is_numeric(arg_type):
                errors.append(ValidationError(f"{path}.args[0]", "floor requires a numeric argument"))
            return ScalarType.INT
        if fn in {"date_diff_days", "age_months_from_date"}:
            if len(args) != 2:
                errors.append(ValidationError(path, f"{fn} expects exactly two arguments"))
                return None
            for index, arg in enumerate(args):
                arg_type = _infer_expr_type(arg, document, f"{path}.args[{index}]", errors)
                if arg_type is not None and not _is_numeric(arg_type):
                    errors.append(
                        ValidationError(
                            f"{path}.args[{index}]",
                            f"{fn} requires numeric day-serial arguments",
                        )
                    )
            return ScalarType.INT
        errors.append(ValidationError(path, f"unsupported helper function '{fn}'"))
        return None

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



def _is_history_id(identifier: str) -> bool:
    return identifier.startswith("h_") or identifier.endswith("_h")
