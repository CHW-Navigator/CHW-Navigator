from __future__ import annotations

from dataclasses import dataclass

from .clinical_ir import ClinicalIRDocument
from .expr_tools import collect_refs


@dataclass(slots=True)
class LintIssue:
    level: str
    path: str
    message: str


def lint_document(
    document: ClinicalIRDocument,
    *,
    allow_output_in_predicates: bool = False,
) -> list[LintIssue]:
    issues: list[LintIssue] = []
    _lint_output_references_in_predicates(document, issues, allow_output_in_predicates)
    _lint_dead_predicates(document, issues)
    _lint_dead_variables(document, issues)
    _lint_history_variables(document, issues)
    _lint_decision_graph(document, issues)
    _lint_phrase_coverage(document, issues)
    _lint_phrase_bindings(document, issues)
    _lint_actions(document, issues)
    _lint_age_normalization(document, issues)
    return issues


def lint_errors(issues: list[LintIssue]) -> list[LintIssue]:
    return [issue for issue in issues if issue.level == "ERROR"]


def lint_warnings(issues: list[LintIssue]) -> list[LintIssue]:
    return [issue for issue in issues if issue.level == "WARNING"]


def _lint_output_references_in_predicates(
    document: ClinicalIRDocument,
    issues: list[LintIssue],
    allow_output_in_predicates: bool,
) -> None:
    if allow_output_in_predicates:
        return
    for predicate in document.predicates.values():
        refs = collect_refs(predicate.expression, {"output"})
        for output_id in sorted(refs):
            issues.append(
                LintIssue(
                    level="ERROR",
                    path=f"predicates.{predicate.id}.expression",
                    message=f"predicate must not reference output '{output_id}'",
                )
            )


def _lint_dead_predicates(document: ClinicalIRDocument, issues: list[LintIssue]) -> None:
    used_predicates: set[str] = set()
    for decision in document.decisions.values():
        used_predicates.update(item for item in decision.inputs_used if item.startswith("p_"))
        for rule in decision.rules:
            used_predicates |= collect_refs(rule.when, {"pred"})
            for assignment in rule.then.values():
                if isinstance(assignment, dict):
                    used_predicates |= collect_refs(assignment, {"pred"})
    for action in document.actions.values():
        if action.when is not None:
            used_predicates |= collect_refs(action.when, {"pred"})
        if action.expression is not None:
            used_predicates |= collect_refs(action.expression, {"pred"})
    for invariant in document.invariants.values():
        used_predicates |= collect_refs(invariant.expression, {"pred"})
    for predicate in document.predicates.values():
        if predicate.id not in used_predicates:
            issues.append(
                LintIssue(
                    level="WARNING",
                    path=f"predicates.{predicate.id}",
                    message="predicate is never referenced by any decision or invariant",
                )
            )


def _lint_dead_variables(document: ClinicalIRDocument, issues: list[LintIssue]) -> None:
    used_variables: set[str] = set()
    for predicate in document.predicates.values():
        used_variables.update(predicate.inputs_used)
        used_variables |= collect_refs(predicate.expression, {"var"})
    for variable in document.variables.values():
        binding = variable.history_binding
        if binding is None:
            continue
        if binding.recorded_at_var is not None:
            used_variables.add(binding.recorded_at_var)
        if binding.must_collect_fresh_when is not None:
            used_variables |= collect_refs(binding.must_collect_fresh_when, {"var"})
        if binding.derivation_expr is not None:
            used_variables |= collect_refs(binding.derivation_expr, {"var"})
    for decision in document.decisions.values():
        used_variables.update(item for item in decision.inputs_used if item.startswith(("v_", "h_", "st_")))
        for rule in decision.rules:
            used_variables |= collect_refs(rule.when, {"var"})
            for assignment in rule.then.values():
                if isinstance(assignment, dict):
                    used_variables |= collect_refs(assignment, {"var"})
    for action in document.actions.values():
        used_variables.update(item for item in action.outputs if item in document.variables)
        if action.when is not None:
            used_variables |= collect_refs(action.when, {"var"})
        if action.expression is not None:
            used_variables |= collect_refs(action.expression, {"var"})
        for mapping in action.mappings:
            used_variables.add(mapping.target_var)
            if mapping.recorded_at_target_var is not None:
                used_variables.add(mapping.recorded_at_target_var)
    for invariant in document.invariants.values():
        used_variables |= collect_refs(invariant.expression, {"var"})
    for variable in document.variables.values():
        if variable.id not in used_variables:
            issues.append(
                LintIssue(
                    level="WARNING",
                    path=f"variables.{variable.id}",
                    message="variable is never referenced by any predicate",
                )
            )


def _lint_history_variables(document: ClinicalIRDocument, issues: list[LintIssue]) -> None:
    for variable in document.variables.values():
        if not _is_history_id(variable.id):
            continue
        if variable.history_binding is None:
            issues.append(
                LintIssue(
                    level="WARNING",
                    path=f"variables.{variable.id}",
                    message="history variable is missing history_binding metadata",
                )
            )
            continue
        if variable.type in {"int", "decimal"} and variable.history_binding.freshness_max_age_days is None:
            issues.append(
                LintIssue(
                    level="WARNING",
                    path=f"variables.{variable.id}.history_binding",
                    message="time-sensitive history variable has no freshness_max_age_days policy",
                )
            )


def _lint_decision_graph(document: ClinicalIRDocument, issues: list[LintIssue]) -> None:
    output_producers: dict[str, str] = {}
    for decision in document.decisions.values():
        for rule in decision.rules:
            for output_id in rule.then:
                output_producers.setdefault(output_id, decision.id)

    graph: dict[str, set[str]] = {decision_id: set() for decision_id in document.decisions}
    for decision in document.decisions.values():
        graph[decision.id].update(decision.depends_on)
        for item in decision.inputs_used:
            if item.startswith("o_") and item in output_producers:
                graph[decision.id].add(output_producers[item])

    temp: set[str] = set()
    perm: set[str] = set()

    def visit(node: str) -> None:
        if node in perm:
            return
        if node in temp:
            issues.append(
                LintIssue(
                    level="ERROR",
                    path=f"decisions.{node}",
                    message="decision dependency cycle detected",
                )
            )
            return
        temp.add(node)
        for child in graph.get(node, set()):
            if child in graph:
                visit(child)
        temp.remove(node)
        perm.add(node)

    for node in graph:
        visit(node)


def _lint_phrase_coverage(document: ClinicalIRDocument, issues: list[LintIssue]) -> None:
    labels = {phrase.entity_id for phrase in document.phrases.values() if phrase.role.value == "label"}
    messages = {phrase.entity_id for phrase in document.phrases.values() if phrase.role.value == "message"}
    guidance = {phrase.entity_id for phrase in document.phrases.values() if phrase.role.value == "guidance"}

    for variable in document.variables.values():
        if variable.id not in labels:
            issues.append(
                LintIssue(
                    level="WARNING",
                    path=f"variables.{variable.id}",
                    message="variable is missing a label phrase",
                )
            )

    for output_id in document.outputs:
        bound = document.phrase_bindings.get(output_id, {})
        has_message = output_id in messages or bool(bound.get("message_key"))
        has_guidance = output_id in guidance or bool(bound.get("guidance_key"))
        if not has_message and not has_guidance:
            issues.append(
                LintIssue(
                    level="WARNING",
                    path=f"outputs.{output_id}",
                    message="output is missing a direct message/guidance phrase or phrase binding",
                )
            )
            continue
        if not has_message:
            issues.append(
                LintIssue(
                    level="WARNING",
                    path=f"outputs.{output_id}",
                    message="output is missing message coverage; add a direct message phrase or message_key binding",
                )
            )
        if not has_guidance:
            issues.append(
                LintIssue(
                    level="WARNING",
                    path=f"outputs.{output_id}",
                    message="output is missing guidance coverage; add a direct guidance phrase or guidance_key binding",
                )
            )

    produced_outputs: set[str] = set()
    for decision in document.decisions.values():
        for rule in decision.rules:
            produced_outputs.update(rule.then.keys())
    for output_id in sorted(produced_outputs):
        if output_id not in document.outputs:
            continue
        has_message = output_id in messages or bool(document.phrase_bindings.get(output_id, {}).get("message_key"))
        has_guidance = output_id in guidance or bool(document.phrase_bindings.get(output_id, {}).get("guidance_key"))
        if not has_message and not has_guidance:
            issues.append(
                LintIssue(
                    level="WARNING",
                    path=f"decisions.output_coverage.{output_id}",
                    message="decision-produced output has no message or guidance coverage",
                )
            )


def _lint_actions(document: ClinicalIRDocument, issues: list[LintIssue]) -> None:
    for action in document.actions.values():
        if action.kind == "create_task" and action.message_key is None:
            issues.append(
                LintIssue(
                    level="WARNING",
                    path=f"actions.{action.id}",
                    message="create_task action is missing a message_key",
                )
            )
        if not action.message_key:
            continue
        phrase = document.phrases.get(action.message_key)
        if phrase is None:
            issues.append(
                LintIssue(
                    level="WARNING",
                    path=f"actions.{action.id}.message_key",
                    message=f"action message_key '{action.message_key}' does not exist in phrases",
                )
            )
            continue
        if phrase.role.value != "message":
            issues.append(
                LintIssue(
                    level="WARNING",
                    path=f"actions.{action.id}.message_key",
                    message=f"action message_key '{action.message_key}' must reference a phrase with role 'message'",
                )
            )
        if phrase.entity_id != action.id:
            issues.append(
                LintIssue(
                    level="WARNING",
                    path=f"actions.{action.id}.message_key",
                    message=f"action message_key '{action.message_key}' points to entity '{phrase.entity_id}' instead of '{action.id}'",
                )
            )


def _lint_phrase_bindings(document: ClinicalIRDocument, issues: list[LintIssue]) -> None:
    for output_id, binding in document.phrase_bindings.items():
        for field_name in ("message_key", "guidance_key"):
            key = binding.get(field_name)
            if key and not key.startswith("m_"):
                issues.append(
                    LintIssue(
                        level="WARNING",
                        path=f"phrase_bindings.{output_id}.{field_name}",
                        message="phrase binding keys must reference m_ phrases",
                    )
                )


def _lint_age_normalization(document: ClinicalIRDocument, issues: list[LintIssue]) -> None:
    for predicate in document.predicates.values():
        if _has_neonatal_month_threshold(predicate.expression):
            issues.append(
                LintIssue(
                    level="WARNING",
                    path=f"predicates.{predicate.id}.expression",
                    message=(
                        "predicate uses an age-in-months neonatal threshold; consider "
                        "st_age_days_effective or date_diff_days(...) for under-2-month precision"
                    ),
                )
            )


def _has_neonatal_month_threshold(expr: dict[str, object] | None) -> bool:
    if not isinstance(expr, dict):
        return False
    kind = expr.get("kind")
    if kind in {"<", "<=", "="}:
        left = expr.get("left")
        right = expr.get("right")
        return _is_age_month_ref(left) and _is_small_literal(right) or _is_age_month_ref(right) and _is_small_literal(left)
    for key in ("left", "right", "arg", "cond", "then", "otherwise"):
        child = expr.get(key)
        if isinstance(child, dict) and _has_neonatal_month_threshold(child):
            return True
    args = expr.get("args")
    if isinstance(args, list):
        return any(isinstance(child, dict) and _has_neonatal_month_threshold(child) for child in args)
    return False


def _is_age_month_ref(expr: object) -> bool:
    return (
        isinstance(expr, dict)
        and expr.get("kind") == "var"
        and isinstance(expr.get("id"), str)
        and "age_month" in str(expr.get("id"))
    )


def _is_small_literal(expr: object) -> bool:
    return (
        isinstance(expr, dict)
        and expr.get("kind") == "literal"
        and isinstance(expr.get("value"), (int, float))
        and float(expr["value"]) <= 2.0
    )


def _is_history_id(identifier: str) -> bool:
    return identifier.startswith("h_") or identifier.endswith("_h")
