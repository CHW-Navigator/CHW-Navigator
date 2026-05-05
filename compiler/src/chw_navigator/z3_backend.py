from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from .clinical_ir import ClinicalIRDocument, MissingnessPolicy, ScalarType

try:
    import z3
except ImportError:  # pragma: no cover - depends on local environment
    z3 = None


class Z3BackendUnavailable(Exception):
    """Raised when the local Python environment does not include z3."""


class Z3LoweringError(Exception):
    """Raised when a supported Clinical IR document cannot be lowered to Z3."""


@dataclass(slots=True)
class Z3Model:
    solver: Any
    document: ClinicalIRDocument
    variables: dict[str, Any]
    variable_missing: dict[str, Any]
    predicates: dict[str, Any]
    predicate_missing: dict[str, Any]
    outputs: dict[str, Any]
    rule_hits: dict[str, Any] = field(default_factory=dict)
    rule_conditions: dict[str, Any] = field(default_factory=dict)
    invariants: dict[str, "CompiledExpr"] = field(default_factory=dict)
    decision_rules: dict[str, list[str]] = field(default_factory=dict)


@dataclass(slots=True)
class Z3Witness:
    inputs: dict[str, Any]
    input_missing: dict[str, bool]
    predicates: dict[str, Any]
    predicate_missing: dict[str, bool]
    outputs: dict[str, Any]
    rule_hits: dict[str, bool]


@dataclass(slots=True)
class Z3CheckResult:
    category: str
    target: str
    ok: bool
    message: str
    witness: Z3Witness | None = None


@dataclass(slots=True)
class Z3AnalysisReport:
    predicate_satisfiability: list[Z3CheckResult] = field(default_factory=list)
    predicate_missingness: list[Z3CheckResult] = field(default_factory=list)
    rule_reachability: list[Z3CheckResult] = field(default_factory=list)
    output_reachability: list[Z3CheckResult] = field(default_factory=list)
    decision_overlaps: list[Z3CheckResult] = field(default_factory=list)
    fallback_reachability: list[Z3CheckResult] = field(default_factory=list)
    invariant_violations: list[Z3CheckResult] = field(default_factory=list)


@dataclass(slots=True)
class Z3GeneratedCase:
    name: str
    category: str
    values: dict[str, Any]
    missing: set[str] = field(default_factory=set)
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CompiledExpr:
    value: Any
    missing: Any


@dataclass(slots=True)
class SmtLibComparisonResult:
    name: str
    ok: bool
    inputs: dict[str, Any]
    missing: list[str] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)
    expected_predicates: dict[str, Any] = field(default_factory=dict)
    expected_outputs: dict[str, Any] = field(default_factory=dict)
    expected_rule_hits: dict[str, Any] = field(default_factory=dict)
    actual_predicates: dict[str, Any] = field(default_factory=dict)
    actual_outputs: dict[str, Any] = field(default_factory=dict)
    actual_rule_hits: dict[str, Any] = field(default_factory=dict)


def _require_z3() -> None:
    if z3 is None:
        raise Z3BackendUnavailable("z3 package is not installed in the current Python environment")


def build_z3_model(document: ClinicalIRDocument, *, enforce_invariants: bool = False) -> Z3Model:
    _require_z3()

    variables = {identifier: _make_symbol(identifier, definition.type) for identifier, definition in document.variables.items()}
    variable_missing = {
        identifier: (z3.Bool(f"missing__{identifier}") if definition.allowed_missingness else z3.BoolVal(False))
        for identifier, definition in document.variables.items()
    }
    predicates = {identifier: z3.Bool(identifier) for identifier in document.predicates}
    predicate_missing = {identifier: z3.Bool(f"missing__{identifier}") for identifier in document.predicates}
    outputs = {identifier: _make_symbol(identifier, definition.type) for identifier, definition in document.outputs.items()}
    rule_hits: dict[str, Any] = {}
    rule_conditions: dict[str, Any] = {}
    invariants: dict[str, CompiledExpr] = {}
    decision_rules: dict[str, list[str]] = {}

    solver = z3.Solver()

    for variable_id, variable_def in document.variables.items():
        _add_domain_constraints(
            solver,
            variables[variable_id],
            variable_missing[variable_id],
            variable_def.type,
            variable_def.domain,
        )

    compiler = _Z3Compiler(document, variables, variable_missing, predicates, predicate_missing, outputs)

    for predicate_id, predicate_def in document.predicates.items():
        compiled = compiler.compile_expr(predicate_def.expression)
        input_missing = _or_list([variable_missing[name] for name in predicate_def.inputs_used])

        if predicate_def.missingness_policy is MissingnessPolicy.TREAT_MISSING_AS_FALSE:
            solver.add(predicate_missing[predicate_id] == z3.BoolVal(False))
            solver.add(
                predicates[predicate_id]
                == z3.If(z3.Or(input_missing, compiled.missing), z3.BoolVal(False), compiled.value)
            )
        elif predicate_def.missingness_policy is MissingnessPolicy.REQUIRE_INPUTS:
            solver.add(predicate_missing[predicate_id] == z3.Or(input_missing, compiled.missing))
            solver.add(
                predicates[predicate_id]
                == z3.If(predicate_missing[predicate_id], z3.BoolVal(False), compiled.value)
            )
        else:
            solver.add(predicate_missing[predicate_id] == compiled.missing)
            solver.add(
                predicates[predicate_id]
                == z3.If(predicate_missing[predicate_id], z3.BoolVal(False), compiled.value)
            )

    for decision in document.decisions.values():
        prior_hits: list[Any] = []
        decision_rules[decision.id] = []
        for rule in decision.rules:
            rule_symbol = z3.Bool(rule.id)
            rule_hits[rule.id] = rule_symbol
            decision_rules[decision.id].append(rule.id)
            if rule.when.get("kind") == "else":
                rule_conditions[rule.id] = z3.BoolVal(True)
                cond_expr = z3.Not(z3.Or(prior_hits)) if prior_hits else z3.BoolVal(True)
            else:
                raw_cond = compiler.compile_condition(rule.when)
                rule_conditions[rule.id] = raw_cond
                cond_expr = z3.And(raw_cond, z3.Not(z3.Or(prior_hits))) if prior_hits else raw_cond
            solver.add(rule_symbol == cond_expr)
            prior_hits.append(rule_symbol)

    for output_id, output_def in document.outputs.items():
        assignments: list[tuple[Any, Any]] = []
        for decision in document.decisions.values():
            for rule in decision.rules:
                if output_id in rule.then:
                    assignments.append(
                        (
                            rule_hits[rule.id],
                            _assignment_to_z3(rule.then[output_id], output_def.type, compiler),
                        )
                    )
        solver.add(outputs[output_id] == _fold_assignments(assignments, output_def.type))

    for invariant in document.invariants.values():
        invariants[invariant.id] = compiler.compile_expr(invariant.expression)
        if enforce_invariants:
            solver.add(z3.And(z3.Not(invariants[invariant.id].missing), invariants[invariant.id].value))

    return Z3Model(
        solver=solver,
        document=document,
        variables=variables,
        variable_missing=variable_missing,
        predicates=predicates,
        predicate_missing=predicate_missing,
        outputs=outputs,
        rule_hits=rule_hits,
        rule_conditions=rule_conditions,
        invariants=invariants,
        decision_rules=decision_rules,
    )


def analyze_document(document: ClinicalIRDocument) -> Z3AnalysisReport:
    _require_z3()
    model = build_z3_model(document, enforce_invariants=False)
    report = Z3AnalysisReport()

    for predicate_id, predicate_symbol in model.predicates.items():
        witness = _solve_witness(
            model,
            z3.And(z3.Not(model.predicate_missing[predicate_id]), predicate_symbol),
        )
        report.predicate_satisfiability.append(
            Z3CheckResult(
                category="predicate_satisfiable",
                target=predicate_id,
                ok=witness is not None,
                message=(
                    f"predicate '{predicate_id}' is satisfiable"
                    if witness is not None
                    else f"predicate '{predicate_id}' is unreachable"
                ),
                witness=witness,
            )
        )
        if model.document.predicates[predicate_id].inputs_used:
            witness = _solve_witness(model, model.predicate_missing[predicate_id])
            report.predicate_missingness.append(
                Z3CheckResult(
                    category="predicate_missing",
                    target=predicate_id,
                    ok=witness is None,
                    message=(
                        f"predicate '{predicate_id}' cannot become missing under current assumptions"
                        if witness is None
                        else f"predicate '{predicate_id}' can become missing"
                    ),
                    witness=witness,
                )
            )

    for rule_id, rule_symbol in model.rule_hits.items():
        witness = _solve_witness(model, rule_symbol)
        report.rule_reachability.append(
            Z3CheckResult(
                category="rule_reachable",
                target=rule_id,
                ok=witness is not None,
                message=(
                    f"rule '{rule_id}' is reachable"
                    if witness is not None
                    else f"rule '{rule_id}' is unreachable"
                ),
                witness=witness,
            )
        )

    for output_id, output_symbol in model.outputs.items():
        output_type = model.document.outputs[output_id].type
        reachability_goal = _non_default_goal(output_symbol, output_type)
        witness = _solve_witness(model, reachability_goal)
        report.output_reachability.append(
            Z3CheckResult(
                category="output_reachable",
                target=output_id,
                ok=witness is not None,
                message=(
                    f"output '{output_id}' can be produced"
                    if witness is not None
                    else f"output '{output_id}' is unreachable"
                ),
                witness=witness,
            )
        )

    for decision_id, rule_ids in model.decision_rules.items():
        non_else_rule_ids = [
            rule_id
            for rule_id in rule_ids
            if model.document.decisions[decision_id].rules[
                _rule_index(model.document.decisions[decision_id].rules, rule_id)
            ].when.get("kind") != "else"
        ]

        for idx, left_rule_id in enumerate(non_else_rule_ids):
            for right_rule_id in non_else_rule_ids[idx + 1 :]:
                overlap_goal = z3.And(
                    model.rule_conditions[left_rule_id],
                    model.rule_conditions[right_rule_id],
                )
                witness = _solve_witness(model, overlap_goal)
                report.decision_overlaps.append(
                    Z3CheckResult(
                        category="decision_overlap",
                        target=f"{decision_id}:{left_rule_id},{right_rule_id}",
                        ok=witness is None,
                        message=(
                            f"rules '{left_rule_id}' and '{right_rule_id}' do not overlap"
                            if witness is None
                            else f"rules '{left_rule_id}' and '{right_rule_id}' overlap"
                        ),
                        witness=witness,
                    )
                )

        raw_non_else_conditions = [
            model.rule_conditions[rule_id]
            for rule_id in non_else_rule_ids
        ]
        gap_goal = z3.Not(z3.Or(raw_non_else_conditions)) if raw_non_else_conditions else z3.BoolVal(True)
        witness = _solve_witness(model, gap_goal)
        report.fallback_reachability.append(
            Z3CheckResult(
                category="fallback_reachable",
                target=decision_id,
                ok=True,
                message=(
                    f"decision '{decision_id}' has reachable fallback space"
                    if witness is not None
                    else f"decision '{decision_id}' fallback is never needed"
                ),
                witness=witness,
            )
        )

    for invariant_id, invariant_expr in model.invariants.items():
        witness = _solve_witness(
            model,
            z3.And(z3.Not(invariant_expr.missing), z3.Not(invariant_expr.value)),
        )
        report.invariant_violations.append(
            Z3CheckResult(
                category="invariant_holds",
                target=invariant_id,
                ok=witness is None,
                message=(
                    f"invariant '{invariant_id}' holds for all supported cases"
                    if witness is None
                    else f"invariant '{invariant_id}' can be violated"
                ),
                witness=witness,
            )
        )

    return report


def generate_patient_for_rule(document: ClinicalIRDocument, rule_id: str) -> Z3Witness | None:
    _require_z3()
    model = build_z3_model(document, enforce_invariants=False)
    if rule_id not in model.rule_hits:
        raise Z3LoweringError(f"unknown rule id '{rule_id}'")
    return _solve_witness(model, model.rule_hits[rule_id])


def generate_test_patients(
    document: ClinicalIRDocument,
    *,
    repeated_count: int = 5,
) -> list[Z3GeneratedCase]:
    _require_z3()
    model = build_z3_model(document, enforce_invariants=False)
    generated: list[Z3GeneratedCase] = []
    seen: set[tuple[str, str]] = set()

    def add_case(case: Z3GeneratedCase | None, *, allow_duplicate_values: bool = False) -> None:
        if case is None:
            return
        if allow_duplicate_values:
            generated.append(case)
            return
        dedupe_key = (case.category, _values_key(case.values, case.missing))
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        generated.append(case)

    for case in _generate_endpoint_cases(model):
        add_case(case)
    for case in _generate_pairwise_module_cases(model):
        add_case(case)
    for case in _generate_cutpoint_cases(model):
        add_case(case)

    no_problem_case = _generate_no_problem_case(model)
    add_case(no_problem_case)

    repeat_seed = no_problem_case
    if repeat_seed is None:
        for candidate in generated:
            if not candidate.missing:
                repeat_seed = candidate
                break
    if repeat_seed is not None:
        for index in range(1, repeated_count + 1):
            add_case(
                Z3GeneratedCase(
                    name=f"repeatability_{index:02d}",
                    category="repeatability",
                    values=dict(repeat_seed.values),
                    missing=set(repeat_seed.missing),
                    tags=["repeatability", f"seed:{repeat_seed.name}"],
                ),
                allow_duplicate_values=True,
            )

    return generated


def _generate_endpoint_cases(model: Z3Model) -> list[Z3GeneratedCase]:
    cases: list[Z3GeneratedCase] = []
    for output_id, symbol in model.outputs.items():
        goal = z3.And(_all_inputs_present(model), _non_default_goal(symbol, model.document.outputs[output_id].type))
        witness = _solve_witness(model, goal)
        case = _witness_to_generated_case(
            witness,
            name=f"endpoint_{output_id}",
            category="endpoint",
            tags=["endpoint", output_id],
        )
        if case is not None:
            cases.append(case)
    return cases


def _generate_pairwise_module_cases(model: Z3Model) -> list[Z3GeneratedCase]:
    module_predicates = _infer_module_presence_predicates(model.document)
    if len(module_predicates) < 2:
        return []

    cases: list[Z3GeneratedCase] = []
    module_names = sorted(module_predicates)
    for left_name, right_name in combinations(module_names, 2):
        pair_terms: list[Any] = [_all_inputs_present(model)]
        pair_terms.extend(_non_urgent_terms(model))
        for module_name in module_names:
            predicate_id = module_predicates[module_name]
            predicate_symbol = model.predicates[predicate_id]
            predicate_present = z3.And(z3.Not(model.predicate_missing[predicate_id]), predicate_symbol)
            if module_name in {left_name, right_name}:
                pair_terms.append(predicate_present)
            else:
                pair_terms.append(z3.Or(model.predicate_missing[predicate_id], z3.Not(predicate_symbol)))
        witness = _solve_witness(model, z3.And(pair_terms))
        case = _witness_to_generated_case(
            witness,
            name=f"pair_{left_name}_{right_name}",
            category="pairwise_modules",
            tags=["pairwise_modules", left_name, right_name],
        )
        if case is not None:
            cases.append(case)
    return cases


def _generate_cutpoint_cases(model: Z3Model) -> list[Z3GeneratedCase]:
    cases: list[Z3GeneratedCase] = []
    seen_cutpoints: set[tuple[str, float]] = set()
    for variable_id, threshold in _collect_numeric_cutpoints(model.document):
        marker = (variable_id, float(threshold))
        if marker in seen_cutpoints:
            continue
        seen_cutpoints.add(marker)
        variable_def = model.document.variables.get(variable_id)
        if variable_def is None:
            continue
        for candidate_value in _neighbor_values(variable_def.type, threshold, variable_def.domain):
            terms: list[Any] = [_all_inputs_present(model), _value_constraint(model, variable_id, candidate_value)]
            terms.extend(_non_urgent_terms(model))
            support_term = _support_goal_for_cutpoint(model, variable_id)
            if support_term is not None:
                terms.append(support_term)
            witness = _solve_witness(model, z3.And(terms))
            case = _witness_to_generated_case(
                witness,
                name=f"cutpoint_{variable_id}_{_format_case_value(candidate_value)}",
                category="cutpoint",
                tags=["cutpoint", variable_id, str(threshold)],
            )
            if case is not None:
                cases.append(case)
    return cases


def _generate_no_problem_case(model: Z3Model) -> Z3GeneratedCase | None:
    terms: list[Any] = [_all_inputs_present(model)]

    for predicate_id in _module_and_danger_predicates(model.document):
        if predicate_id in model.predicates:
            terms.append(z3.Or(model.predicate_missing[predicate_id], z3.Not(model.predicates[predicate_id])))

    for variable_id, definition in model.document.variables.items():
        symbol = model.variables[variable_id]
        if definition.type is ScalarType.BOOL:
            terms.append(symbol == z3.BoolVal(False))
        elif definition.type is ScalarType.INT:
            terms.append(symbol == z3.IntVal(_baseline_numeric_value(definition)))
        elif definition.type is ScalarType.DECIMAL:
            terms.append(symbol == z3.RealVal(_baseline_numeric_value(definition)))
        elif definition.type in {ScalarType.STRING, ScalarType.STRING_KEY, ScalarType.ENUM}:
            baseline = _baseline_string_value(definition)
            terms.append(symbol == z3.StringVal(baseline))

    witness = _solve_witness(model, z3.And(terms))
    return _witness_to_generated_case(
        witness,
        name="no_problems",
        category="no_problems",
        tags=["no_problems", "baseline"],
    )


def _infer_module_presence_predicates(document: ClinicalIRDocument) -> dict[str, str]:
    modules: dict[str, str] = {}
    for predicate_id in document.predicates:
        if predicate_id.startswith("p_has_"):
            modules[predicate_id[len("p_has_") :]] = predicate_id
    return modules


def _collect_numeric_cutpoints(document: ClinicalIRDocument) -> list[tuple[str, int | float]]:
    cutpoints: list[tuple[str, int | float]] = []
    for predicate in document.predicates.values():
        cutpoints.extend(_collect_numeric_cutpoints_from_expr(predicate.expression))
    for decision in document.decisions.values():
        for rule in decision.rules:
            cutpoints.extend(_collect_numeric_cutpoints_from_expr(rule.when))
            for value in rule.then.values():
                if isinstance(value, dict) and "kind" in value:
                    cutpoints.extend(_collect_numeric_cutpoints_from_expr(value))
    for invariant in document.invariants.values():
        cutpoints.extend(_collect_numeric_cutpoints_from_expr(invariant.expression))
    return cutpoints


def _collect_numeric_cutpoints_from_expr(expr: dict[str, Any]) -> list[tuple[str, int | float]]:
    kind = expr.get("kind")
    if kind in {"<", "<=", ">", ">=", "=", "!="}:
        left = expr.get("left")
        right = expr.get("right")
        if isinstance(left, dict) and isinstance(right, dict):
            if left.get("kind") == "var" and right.get("kind") == "literal" and isinstance(right.get("value"), (int, float)):
                return [(str(left["id"]), right["value"])]
            if right.get("kind") == "var" and left.get("kind") == "literal" and isinstance(left.get("value"), (int, float)):
                return [(str(right["id"]), left["value"])]
    if kind in {"and", "or", "exactly_one"}:
        found: list[tuple[str, int | float]] = []
        for arg in expr.get("args", []):
            if isinstance(arg, dict):
                found.extend(_collect_numeric_cutpoints_from_expr(arg))
        return found
    if kind == "not":
        arg = expr.get("arg")
        return _collect_numeric_cutpoints_from_expr(arg) if isinstance(arg, dict) else []
    if kind == "if":
        found: list[tuple[str, int | float]] = []
        for key in ("cond", "then", "else"):
            value = expr.get(key)
            if isinstance(value, dict):
                found.extend(_collect_numeric_cutpoints_from_expr(value))
        return found
    if kind in {"+", "-", "*", "/"}:
        found: list[tuple[str, int | float]] = []
        left = expr.get("left")
        right = expr.get("right")
        if isinstance(left, dict):
            found.extend(_collect_numeric_cutpoints_from_expr(left))
        if isinstance(right, dict):
            found.extend(_collect_numeric_cutpoints_from_expr(right))
        return found
    return []


def _neighbor_values(scalar_type: ScalarType, threshold: int | float, domain: Any) -> list[int | float]:
    if scalar_type is ScalarType.INT:
        candidates: list[int | float] = [int(threshold) - 1, int(threshold), int(threshold) + 1]
    elif scalar_type is ScalarType.DECIMAL:
        candidates = [round(float(threshold) - 0.1, 1), round(float(threshold), 1), round(float(threshold) + 0.1, 1)]
    else:
        return []

    filtered: list[int | float] = []
    for candidate in candidates:
        if domain is not None and domain.min is not None and candidate < domain.min:
            continue
        if domain is not None and domain.max is not None and candidate > domain.max:
            continue
        if candidate not in filtered:
            filtered.append(candidate)
    return filtered


def _support_goal_for_cutpoint(model: Z3Model, variable_id: str) -> Any | None:
    module_name = _module_name_from_variable(variable_id)
    if module_name is None:
        return None
    predicate_id = f"p_has_{module_name}"
    if predicate_id in model.predicates:
        return z3.And(z3.Not(model.predicate_missing[predicate_id]), model.predicates[predicate_id])
    boolean_variable_id = f"v_has_{module_name}"
    if boolean_variable_id in model.variables:
        return z3.And(z3.Not(model.variable_missing[boolean_variable_id]), model.variables[boolean_variable_id])
    return None


def _module_name_from_variable(variable_id: str) -> str | None:
    if not variable_id.startswith("v_"):
        return None
    stem = variable_id[len("v_") :]
    for suffix in ("_days", "_duration", "_temp_c", "_count", "_months"):
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return None


def _module_and_danger_predicates(document: ClinicalIRDocument) -> list[str]:
    predicate_ids = [predicate_id for predicate_id in document.predicates if predicate_id.startswith("p_has_")]
    if "p_danger_sign" in document.predicates:
        predicate_ids.append("p_danger_sign")
    return sorted(set(predicate_ids))


def _baseline_numeric_value(definition: Any) -> int | float:
    if definition.domain is not None and definition.domain.min is not None:
        return definition.domain.min
    return 0


def _baseline_string_value(definition: Any) -> str:
    if definition.domain is not None and definition.domain.values:
        return definition.domain.values[0]
    return ""


def _non_urgent_terms(model: Z3Model) -> list[Any]:
    terms: list[Any] = []
    if "p_danger_sign" in model.predicates:
        terms.append(z3.Or(model.predicate_missing["p_danger_sign"], z3.Not(model.predicates["p_danger_sign"])))
    elif "v_has_danger_sign" in model.variables:
        terms.append(z3.And(z3.Not(model.variable_missing["v_has_danger_sign"]), z3.Not(model.variables["v_has_danger_sign"])))
    return terms


def _all_inputs_present(model: Z3Model) -> Any:
    return z3.And([z3.Not(symbol) for symbol in model.variable_missing.values()]) if model.variable_missing else z3.BoolVal(True)


def _value_constraint(model: Z3Model, variable_id: str, value: int | float) -> Any:
    variable_def = model.document.variables[variable_id]
    return z3.And(
        z3.Not(model.variable_missing[variable_id]),
        model.variables[variable_id] == _literal_to_z3(value, variable_def.type),
    )


def _witness_to_generated_case(
    witness: Z3Witness | None,
    *,
    name: str,
    category: str,
    tags: list[str],
) -> Z3GeneratedCase | None:
    if witness is None or any(witness.input_missing.values()):
        return None
    return Z3GeneratedCase(
        name=name,
        category=category,
        values={key: value for key, value in witness.inputs.items() if value is not None},
        missing=set(),
        tags=tags,
    )


def _format_case_value(value: int | float) -> str:
    return str(value).replace("-", "neg_").replace(".", "_")


def _values_key(values: dict[str, Any], missing: set[str]) -> str:
    items = [f"{key}={values[key]!r}" for key in sorted(values)]
    if missing:
        items.append(f"missing={sorted(missing)!r}")
    return "|".join(items)


def export_smt2(document: ClinicalIRDocument, *, enforce_invariants: bool = False) -> str:
    _require_z3()
    model = build_z3_model(document, enforce_invariants=enforce_invariants)
    return model.solver.to_smt2()


def write_smt2(document: ClinicalIRDocument, output_path: str, *, enforce_invariants: bool = False) -> str:
    from pathlib import Path

    text = export_smt2(document, enforce_invariants=enforce_invariants)
    path = Path(output_path)
    path.write_text(text, encoding="utf-8")
    return str(path)


def evaluate_patient(
    document: ClinicalIRDocument,
    values: dict[str, Any],
    missing: set[str] | None = None,
) -> Z3Witness:
    _require_z3()
    model = build_z3_model(document, enforce_invariants=False)
    solver = z3.Solver()
    solver.add(model.solver.assertions())

    missing_set = missing or set()
    for variable_id, symbol in model.variables.items():
        is_missing = variable_id in missing_set
        solver.add(model.variable_missing[variable_id] == z3.BoolVal(is_missing))
        if not is_missing:
            if variable_id not in values:
                raise Z3LoweringError(f"missing concrete value for variable '{variable_id}'")
            solver.add(symbol == _literal_to_z3(values[variable_id], document.variables[variable_id].type))

    if solver.check() != z3.sat:
        raise Z3LoweringError("patient assignment is inconsistent with the Clinical IR constraints")
    return _model_to_witness(model, solver.model())


def evaluate_smt2_text(
    document: ClinicalIRDocument,
    smt2_text: str,
    values: dict[str, Any],
    missing: set[str] | None = None,
) -> Z3Witness:
    _require_z3()
    symbols = _document_symbols(document)
    solver = z3.Solver()
    solver.add(z3.parse_smt2_string(smt2_text))
    _constrain_patient_assignment(
        solver,
        document,
        symbols["variables"],
        symbols["variable_missing"],
        values,
        missing,
    )
    if solver.check() != z3.sat:
        raise Z3LoweringError("SMT-LIB candidate is inconsistent with the Clinical IR constraints for this patient")
    return _symbols_to_witness(document, symbols, solver.model())


def evaluate_smt2_file(
    document: ClinicalIRDocument,
    smt2_path: str,
    values: dict[str, Any],
    missing: set[str] | None = None,
) -> Z3Witness:
    from pathlib import Path

    return evaluate_smt2_text(document, Path(smt2_path).read_text(encoding="utf-8"), values, missing)


def compare_smt2_text(
    document: ClinicalIRDocument,
    smt2_text: str,
    patient_cases: list[Any],
    *,
    label: str = "SMT-LIB",
) -> list[SmtLibComparisonResult]:
    _require_z3()
    from .evaluator import evaluate_document

    results: list[SmtLibComparisonResult] = []
    for case in patient_cases:
        overlap = case.missing & set(case.values)
        if overlap:
            raise Z3LoweringError(
                f"comparison case '{case.name}' marks inputs as missing and present at the same time: {sorted(overlap)}"
            )

        expected_eval = evaluate_document(document, case.values, case.missing)
        actual_eval = evaluate_smt2_text(document, smt2_text, case.values, case.missing)
        expected_rule_hits = {
            rule.id: False
            for decision in document.decisions.values()
            for rule in decision.rules
        }
        for trace in expected_eval.decisions:
            if trace.fired_rule_id is not None:
                expected_rule_hits[trace.fired_rule_id] = True

        mismatches: list[str] = []
        mismatches.extend(_compare_simple_dicts(f"{label} predicates", expected_eval.predicates, actual_eval.predicates))
        mismatches.extend(_compare_simple_dicts(f"{label} outputs", expected_eval.outputs, actual_eval.outputs))
        mismatches.extend(_compare_simple_dicts(f"{label} rule hits", expected_rule_hits, actual_eval.rule_hits))

        results.append(
            SmtLibComparisonResult(
                name=case.name,
                ok=not mismatches,
                inputs=case.values,
                missing=sorted(case.missing),
                mismatches=mismatches,
                expected_predicates=expected_eval.predicates,
                expected_outputs=expected_eval.outputs,
                expected_rule_hits=expected_rule_hits,
                actual_predicates=actual_eval.predicates,
                actual_outputs=actual_eval.outputs,
                actual_rule_hits=actual_eval.rule_hits,
            )
        )
    return results


def compare_smt2_file(
    document: ClinicalIRDocument,
    smt2_path: str,
    patient_cases: list[Any],
    *,
    label: str = "SMT-LIB",
) -> list[SmtLibComparisonResult]:
    from pathlib import Path

    return compare_smt2_text(document, Path(smt2_path).read_text(encoding="utf-8"), patient_cases, label=label)


class _Z3Compiler:
    def __init__(
        self,
        document: ClinicalIRDocument,
        variables: dict[str, Any],
        variable_missing: dict[str, Any],
        predicates: dict[str, Any],
        predicate_missing: dict[str, Any],
        outputs: dict[str, Any],
    ) -> None:
        self.document = document
        self.variables = variables
        self.variable_missing = variable_missing
        self.predicates = predicates
        self.predicate_missing = predicate_missing
        self.outputs = outputs

    def compile_expr(self, expr: dict[str, Any]) -> CompiledExpr:
        kind = expr["kind"]
        if kind == "literal":
            return CompiledExpr(
                value=_typed_literal(expr["value"], expr.get("type")),
                missing=z3.BoolVal(False),
            )
        if kind == "var":
            return CompiledExpr(
                value=self.variables[expr["id"]],
                missing=self.variable_missing[expr["id"]],
            )
        if kind == "const":
            const_def = self.document.constants[expr["id"]]
            return CompiledExpr(
                value=_literal_to_z3(const_def.value, const_def.type),
                missing=z3.BoolVal(False),
            )
        if kind == "pred":
            return CompiledExpr(
                value=self.predicates[expr["id"]],
                missing=self.predicate_missing[expr["id"]],
            )
        if kind == "output":
            return CompiledExpr(
                value=self.outputs[expr["id"]],
                missing=z3.BoolVal(False),
            )
        if kind == "not":
            compiled = self.compile_expr(expr["arg"])
            return CompiledExpr(value=z3.Not(compiled.value), missing=compiled.missing)
        if kind == "and":
            compiled = [self.compile_expr(arg) for arg in expr["args"]]
            any_false = _or_list([z3.And(z3.Not(item.missing), z3.Not(item.value)) for item in compiled])
            any_missing = _or_list([item.missing for item in compiled])
            return CompiledExpr(
                value=z3.And([item.value for item in compiled]),
                missing=z3.And(z3.Not(any_false), any_missing),
            )
        if kind == "or":
            compiled = [self.compile_expr(arg) for arg in expr["args"]]
            any_true = _or_list([z3.And(z3.Not(item.missing), item.value) for item in compiled])
            any_missing = _or_list([item.missing for item in compiled])
            return CompiledExpr(
                value=any_true,
                missing=z3.And(z3.Not(any_true), any_missing),
            )
        if kind == "exactly_one":
            compiled = [self.compile_expr(arg) for arg in expr["args"]]
            return CompiledExpr(
                value=z3.PbEq([(item.value, 1) for item in compiled], 1),
                missing=_or_list([item.missing for item in compiled]),
            )
        if kind == "if":
            cond = self.compile_expr(expr["cond"])
            when_true = self.compile_expr(expr["then"])
            when_false = self.compile_expr(expr["else"])
            return CompiledExpr(
                value=z3.If(cond.value, when_true.value, when_false.value),
                missing=z3.Or(
                    cond.missing,
                    z3.If(cond.value, when_true.missing, when_false.missing),
                ),
            )
        if kind == "=":
            return _compile_compare("=", self.compile_expr(expr["left"]), self.compile_expr(expr["right"]))
        if kind == "!=":
            return _compile_compare("!=", self.compile_expr(expr["left"]), self.compile_expr(expr["right"]))
        if kind == "<":
            return _compile_compare("<", self.compile_expr(expr["left"]), self.compile_expr(expr["right"]))
        if kind == "<=":
            return _compile_compare("<=", self.compile_expr(expr["left"]), self.compile_expr(expr["right"]))
        if kind == ">":
            return _compile_compare(">", self.compile_expr(expr["left"]), self.compile_expr(expr["right"]))
        if kind == ">=":
            return _compile_compare(">=", self.compile_expr(expr["left"]), self.compile_expr(expr["right"]))
        if kind == "+":
            return _compile_arithmetic("+", self.compile_expr(expr["left"]), self.compile_expr(expr["right"]))
        if kind == "-":
            return _compile_arithmetic("-", self.compile_expr(expr["left"]), self.compile_expr(expr["right"]))
        if kind == "*":
            return _compile_arithmetic("*", self.compile_expr(expr["left"]), self.compile_expr(expr["right"]))
        if kind == "/":
            return _compile_arithmetic("/", self.compile_expr(expr["left"]), self.compile_expr(expr["right"]))
        if kind == "selected":
            raise Z3LoweringError("selected() is not yet supported in the initial Z3 backend")
        raise Z3LoweringError(f"unsupported expression kind '{kind}'")

    def compile_condition(self, expr: dict[str, Any]) -> Any:
        compiled = self.compile_expr(expr)
        return z3.And(z3.Not(compiled.missing), compiled.value)


def _make_symbol(identifier: str, scalar_type: ScalarType) -> Any:
    if scalar_type is ScalarType.BOOL:
        return z3.Bool(identifier)
    if scalar_type is ScalarType.INT:
        return z3.Int(identifier)
    if scalar_type is ScalarType.DECIMAL:
        return z3.Real(identifier)
    if scalar_type in {ScalarType.STRING, ScalarType.STRING_KEY, ScalarType.ENUM}:
        return z3.String(identifier)
    raise Z3LoweringError(f"unsupported scalar type '{scalar_type}'")


def _typed_literal(value: Any, literal_type: str | None) -> Any:
    if isinstance(value, bool):
        return z3.BoolVal(value)
    if isinstance(value, int):
        return z3.IntVal(value)
    if isinstance(value, float):
        return z3.RealVal(value)
    if isinstance(value, str):
        return z3.StringVal(value)
    if literal_type == "bool":
        return z3.BoolVal(bool(value))
    raise Z3LoweringError(f"unsupported literal value '{value!r}'")


def _literal_to_z3(value: Any, scalar_type: ScalarType) -> Any:
    if scalar_type is ScalarType.BOOL:
        return z3.BoolVal(bool(value))
    if scalar_type is ScalarType.INT:
        return z3.IntVal(int(value))
    if scalar_type is ScalarType.DECIMAL:
        return z3.RealVal(value)
    if scalar_type in {ScalarType.STRING, ScalarType.STRING_KEY, ScalarType.ENUM}:
        return z3.StringVal(str(value))
    raise Z3LoweringError(f"unsupported scalar type '{scalar_type}'")


def _assignment_to_z3(value: Any, scalar_type: ScalarType, compiler: "_Z3Compiler") -> Any:
    if isinstance(value, dict) and "kind" in value:
        compiled = compiler.compile_expr(value)
        return z3.If(compiled.missing, _default_value(scalar_type), compiled.value)
    return _literal_to_z3(value, scalar_type)


def _default_value(output_type: ScalarType) -> Any:
    if output_type is ScalarType.BOOL:
        return z3.BoolVal(False)
    if output_type is ScalarType.INT:
        return z3.IntVal(0)
    if output_type is ScalarType.DECIMAL:
        return z3.RealVal(0)
    if output_type in {ScalarType.STRING, ScalarType.STRING_KEY, ScalarType.ENUM}:
        return z3.StringVal("")
    raise Z3LoweringError(f"unsupported scalar type '{output_type}'")


def _fold_assignments(assignments: list[tuple[Any, Any]], output_type: ScalarType) -> Any:
    expr = _default_value(output_type)
    for condition, value in reversed(assignments):
        expr = z3.If(condition, value, expr)
    return expr


def _add_domain_constraints(
    solver: Any,
    symbol: Any,
    missing_symbol: Any,
    scalar_type: ScalarType,
    domain: Any,
) -> None:
    if domain is None:
        return
    if scalar_type in {ScalarType.INT, ScalarType.DECIMAL}:
        if domain.min is not None:
            solver.add(z3.Implies(z3.Not(missing_symbol), symbol >= domain.min))
        if domain.max is not None:
            solver.add(z3.Implies(z3.Not(missing_symbol), symbol <= domain.max))
    if domain.values is not None:
        solver.add(
            z3.Implies(
                z3.Not(missing_symbol),
                z3.Or([symbol == z3.StringVal(value) for value in domain.values]),
            )
        )


def _rule_index(rules: list[Any], rule_id: str) -> int:
    for index, rule in enumerate(rules):
        if rule.id == rule_id:
            return index
    raise Z3LoweringError(f"unknown rule id '{rule_id}'")


def _non_default_goal(symbol: Any, output_type: ScalarType) -> Any:
    if output_type is ScalarType.BOOL:
        return symbol
    if output_type is ScalarType.INT:
        return symbol != z3.IntVal(0)
    if output_type is ScalarType.DECIMAL:
        return symbol != z3.RealVal(0)
    if output_type in {ScalarType.STRING, ScalarType.STRING_KEY, ScalarType.ENUM}:
        return symbol != z3.StringVal("")
    raise Z3LoweringError(f"unsupported scalar type '{output_type}'")


def _solve_witness(model: Z3Model, goal: Any) -> Z3Witness | None:
    solver = z3.Solver()
    solver.add(model.solver.assertions())
    solver.add(goal)
    if solver.check() != z3.sat:
        return None
    return _model_to_witness(model, solver.model())


def _model_to_witness(model: Z3Model, z3_model: Any) -> Z3Witness:
    symbols = {
        "variables": model.variables,
        "variable_missing": model.variable_missing,
        "predicates": model.predicates,
        "predicate_missing": model.predicate_missing,
        "outputs": model.outputs,
        "rule_hits": model.rule_hits,
    }
    return _symbols_to_witness(model.document, symbols, z3_model)


def _symbols_to_witness(document: ClinicalIRDocument, symbols: dict[str, dict[str, Any]], z3_model: Any) -> Z3Witness:
    input_missing = {
        variable_id: bool(z3.is_true(z3_model.eval(symbol, model_completion=True)))
        for variable_id, symbol in symbols["variable_missing"].items()
    }
    predicate_missing = {
        predicate_id: bool(z3.is_true(z3_model.eval(symbol, model_completion=True)))
        for predicate_id, symbol in symbols["predicate_missing"].items()
    }
    return Z3Witness(
        inputs={
            variable_id: (
                None
                if input_missing[variable_id]
                else _decode_value(z3_model.eval(symbol, model_completion=True))
            )
            for variable_id, symbol in symbols["variables"].items()
        },
        input_missing=input_missing,
        predicates={
            predicate_id: (
                None
                if predicate_missing[predicate_id]
                else bool(z3.is_true(z3_model.eval(symbol, model_completion=True)))
            )
            for predicate_id, symbol in symbols["predicates"].items()
        },
        predicate_missing=predicate_missing,
        outputs={
            output_id: _decode_value(z3_model.eval(symbol, model_completion=True))
            for output_id, symbol in symbols["outputs"].items()
        },
        rule_hits={
            rule_id: bool(z3.is_true(z3_model.eval(symbol, model_completion=True)))
            for rule_id, symbol in symbols["rule_hits"].items()
        },
    )


def _decode_value(value: Any) -> Any:
    if z3.is_true(value):
        return True
    if z3.is_false(value):
        return False
    if z3.is_int_value(value):
        return value.as_long()
    if z3.is_rational_value(value):
        if value.denominator_as_long() == 1:
            return value.numerator_as_long()
        return value.as_decimal(12)
    if z3.is_string_value(value):
        return value.as_string()
    return str(value)


def _or_list(items: list[Any]) -> Any:
    return z3.Or(items) if items else z3.BoolVal(False)


def _compile_compare(op: str, left: CompiledExpr, right: CompiledExpr) -> CompiledExpr:
    if op == "=":
        value = left.value == right.value
    elif op == "!=":
        value = left.value != right.value
    elif op == "<":
        value = left.value < right.value
    elif op == "<=":
        value = left.value <= right.value
    elif op == ">":
        value = left.value > right.value
    elif op == ">=":
        value = left.value >= right.value
    else:
        raise Z3LoweringError(f"unsupported comparison operator '{op}'")
    return CompiledExpr(value=value, missing=z3.Or(left.missing, right.missing))


def _compile_arithmetic(op: str, left: CompiledExpr, right: CompiledExpr) -> CompiledExpr:
    if op == "+":
        value = left.value + right.value
    elif op == "-":
        value = left.value - right.value
    elif op == "*":
        value = left.value * right.value
    elif op == "/":
        value = left.value / right.value
    else:
        raise Z3LoweringError(f"unsupported arithmetic operator '{op}'")
    return CompiledExpr(value=value, missing=z3.Or(left.missing, right.missing))


def _document_symbols(document: ClinicalIRDocument) -> dict[str, dict[str, Any]]:
    _require_z3()
    variables = {identifier: _make_symbol(identifier, definition.type) for identifier, definition in document.variables.items()}
    variable_missing = {
        identifier: (z3.Bool(f"missing__{identifier}") if definition.allowed_missingness else z3.BoolVal(False))
        for identifier, definition in document.variables.items()
    }
    predicates = {identifier: z3.Bool(identifier) for identifier in document.predicates}
    predicate_missing = {identifier: z3.Bool(f"missing__{identifier}") for identifier in document.predicates}
    outputs = {identifier: _make_symbol(identifier, definition.type) for identifier, definition in document.outputs.items()}
    rule_hits = {
        rule.id: z3.Bool(rule.id)
        for decision in document.decisions.values()
        for rule in decision.rules
    }
    return {
        "variables": variables,
        "variable_missing": variable_missing,
        "predicates": predicates,
        "predicate_missing": predicate_missing,
        "outputs": outputs,
        "rule_hits": rule_hits,
    }


def _constrain_patient_assignment(
    solver: Any,
    document: ClinicalIRDocument,
    variables: dict[str, Any],
    variable_missing: dict[str, Any],
    values: dict[str, Any],
    missing: set[str] | None,
) -> None:
    missing_set = missing or set()
    for variable_id, symbol in variables.items():
        is_missing = variable_id in missing_set
        solver.add(variable_missing[variable_id] == z3.BoolVal(is_missing))
        if not is_missing:
            if variable_id not in values:
                raise Z3LoweringError(f"missing concrete value for variable '{variable_id}'")
            solver.add(symbol == _literal_to_z3(values[variable_id], document.variables[variable_id].type))


def _compare_simple_dicts(label: str, expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []
    keys = sorted(set(expected) | set(actual))
    for key in keys:
        expected_value = expected.get(key)
        actual_value = actual.get(key)
        if actual_value != expected_value:
            mismatches.append(f"{label} mismatch for '{key}': expected {expected_value!r}, got {actual_value!r}")
    return mismatches
