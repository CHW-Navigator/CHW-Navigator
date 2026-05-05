from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .clinical_ir import ClinicalIRDocument, MissingnessPolicy, ScalarType


MISSING = object()


class EvaluationError(Exception):
    """Raised when the reference interpreter cannot evaluate an input or expression."""


@dataclass(slots=True)
class PatientInput:
    values: dict[str, Any]
    missing: set[str] = field(default_factory=set)


@dataclass(slots=True)
class DecisionTrace:
    decision_id: str
    fired_rule_id: str | None


@dataclass(slots=True)
class EvaluationResult:
    predicates: dict[str, Any]
    outputs: dict[str, Any]
    decisions: list[DecisionTrace]
    invariants: dict[str, Any]


def evaluate_document(
    document: ClinicalIRDocument,
    values: dict[str, Any],
    missing: set[str] | None = None,
) -> EvaluationResult:
    interpreter = _Interpreter(document, PatientInput(values=values, missing=missing or set()))
    return interpreter.run()


class _Interpreter:
    def __init__(self, document: ClinicalIRDocument, patient: PatientInput) -> None:
        self.document = document
        self.patient = patient
        self.predicate_cache: dict[str, Any] = {}
        self.outputs: dict[str, Any] = {
            output_id: _default_output_value(output_def.type)
            for output_id, output_def in document.outputs.items()
        }
        self.decision_trace: list[DecisionTrace] = []

    def run(self) -> EvaluationResult:
        self._validate_input()
        for predicate_id in self.document.predicates:
            self._eval_predicate(predicate_id)

        for decision in self.document.decisions.values():
            fired_rule_id = None
            for rule in decision.rules:
                matched = True if rule.when.get("kind") == "else" else self._truthy(
                    self._eval_expr(rule.when)
                )
                if matched is True:
                    fired_rule_id = rule.id
                    for output_id, raw_value in rule.then.items():
                        self.outputs[output_id] = self._eval_assignment(raw_value)
                    break
            self.decision_trace.append(
                DecisionTrace(decision_id=decision.id, fired_rule_id=fired_rule_id)
            )

        invariants = {
            invariant.id: self._eval_expr(invariant.expression)
            for invariant in self.document.invariants.values()
        }

        return EvaluationResult(
            predicates=dict(self.predicate_cache),
            outputs=dict(self.outputs),
            decisions=self.decision_trace,
            invariants=invariants,
        )

    def _validate_input(self) -> None:
        for variable_id, variable_def in self.document.variables.items():
            is_missing = variable_id in self.patient.missing or variable_id not in self.patient.values
            if is_missing and not variable_def.allowed_missingness:
                raise EvaluationError(f"required variable '{variable_id}' is missing")
            if not is_missing:
                _validate_value(variable_id, self.patient.values[variable_id], variable_def.type, variable_def.domain)

    def _eval_assignment(self, raw_value: Any) -> Any:
        if isinstance(raw_value, dict) and "kind" in raw_value:
            return self._eval_expr(raw_value)
        return raw_value

    def _eval_expr(self, expr: dict[str, Any]) -> Any:
        kind = expr["kind"]

        if kind == "literal":
            return expr.get("value")
        if kind == "else":
            return True
        if kind == "var":
            return self._get_variable_value(expr["id"])
        if kind == "const":
            return self.document.constants[expr["id"]].value
        if kind == "pred":
            return self._eval_predicate(expr["id"])
        if kind == "output":
            return self.outputs[expr["id"]]

        if kind == "not":
            return _tri_not(self._eval_expr(expr["arg"]))
        if kind == "and":
            return _tri_and([self._eval_expr(arg) for arg in expr["args"]])
        if kind == "or":
            return _tri_or([self._eval_expr(arg) for arg in expr["args"]])
        if kind == "exactly_one":
            return _tri_exactly_one([self._eval_expr(arg) for arg in expr["args"]])

        if kind == "if":
            cond_value = self._eval_expr(expr["cond"])
            if cond_value is True:
                return self._eval_expr(expr["then"])
            if cond_value is False:
                return self._eval_expr(expr["else"])
            return None

        if kind in {"=", "!=", "<", "<=", ">", ">=", "+", "-", "*", "/"}:
            left = self._eval_expr(expr["left"])
            right = self._eval_expr(expr["right"])
            return _eval_binary(kind, left, right)

        if kind == "selected":
            target = self._eval_expr(expr["target"])
            choice = expr["choice"]
            if target is None or target is MISSING:
                return None
            if isinstance(target, (list, tuple, set)):
                return choice in target
            if isinstance(target, str):
                return choice in target.split()
            raise EvaluationError(f"selected() target must be a string or list, got {type(target).__name__}")

        raise EvaluationError(f"unsupported expression kind '{kind}'")

    def _eval_predicate(self, predicate_id: str) -> Any:
        if predicate_id in self.predicate_cache:
            return self.predicate_cache[predicate_id]

        predicate = self.document.predicates[predicate_id]
        missing_inputs = [identifier for identifier in predicate.inputs_used if self._is_missing(identifier)]

        if missing_inputs:
            if predicate.missingness_policy is MissingnessPolicy.REQUIRE_INPUTS:
                value = None
            elif predicate.missingness_policy is MissingnessPolicy.TREAT_MISSING_AS_FALSE:
                value = False
            else:
                value = self._eval_expr(predicate.expression)
        else:
            value = self._eval_expr(predicate.expression)

        self.predicate_cache[predicate_id] = value
        return value

    def _get_variable_value(self, variable_id: str) -> Any:
        if self._is_missing(variable_id):
            return MISSING
        return self.patient.values[variable_id]

    def _is_missing(self, variable_id: str) -> bool:
        return variable_id in self.patient.missing or variable_id not in self.patient.values

    @staticmethod
    def _truthy(value: Any) -> bool | None:
        if value is MISSING:
            return None
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        raise EvaluationError(f"expected Boolean condition, got {type(value).__name__}")


def _default_output_value(output_type: ScalarType) -> Any:
    if output_type is ScalarType.BOOL:
        return False
    return None


def _validate_value(variable_id: str, value: Any, scalar_type: ScalarType, domain: Any) -> None:
    if scalar_type is ScalarType.BOOL:
        if not isinstance(value, bool):
            raise EvaluationError(f"variable '{variable_id}' must be bool, got {type(value).__name__}")
    elif scalar_type is ScalarType.INT:
        if not isinstance(value, int) or isinstance(value, bool):
            raise EvaluationError(f"variable '{variable_id}' must be int, got {type(value).__name__}")
    elif scalar_type is ScalarType.DECIMAL:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise EvaluationError(f"variable '{variable_id}' must be decimal, got {type(value).__name__}")
    elif scalar_type in {ScalarType.STRING, ScalarType.STRING_KEY, ScalarType.ENUM}:
        if not isinstance(value, str):
            raise EvaluationError(f"variable '{variable_id}' must be string-like, got {type(value).__name__}")

    if domain is None:
        return
    if domain.min is not None and value < domain.min:
        raise EvaluationError(f"variable '{variable_id}' value {value!r} is below domain minimum {domain.min}")
    if domain.max is not None and value > domain.max:
        raise EvaluationError(f"variable '{variable_id}' value {value!r} is above domain maximum {domain.max}")
    if domain.values is not None and value not in domain.values:
        raise EvaluationError(f"variable '{variable_id}' value {value!r} is not in allowed domain values")


def _eval_binary(kind: str, left: Any, right: Any) -> Any:
    if left is MISSING or right is MISSING or left is None or right is None:
        return None
    if kind == "=":
        return left == right
    if kind == "!=":
        return left != right
    if kind == "<":
        return left < right
    if kind == "<=":
        return left <= right
    if kind == ">":
        return left > right
    if kind == ">=":
        return left >= right
    if kind == "+":
        return left + right
    if kind == "-":
        return left - right
    if kind == "*":
        return left * right
    if kind == "/":
        return left / right
    raise EvaluationError(f"unsupported binary operator '{kind}'")


def _tri_not(value: Any) -> bool | None:
    if value is MISSING or value is None:
        return None
    return not value


def _tri_and(values: list[Any]) -> bool | None:
    saw_unknown = False
    for value in values:
        if value is False:
            return False
        if value is MISSING or value is None:
            saw_unknown = True
    return None if saw_unknown else True


def _tri_or(values: list[Any]) -> bool | None:
    saw_unknown = False
    for value in values:
        if value is True:
            return True
        if value is MISSING or value is None:
            saw_unknown = True
    return None if saw_unknown else False


def _tri_exactly_one(values: list[Any]) -> bool | None:
    true_count = sum(1 for value in values if value is True)
    unknown_count = sum(1 for value in values if value is MISSING or value is None)

    if true_count > 1:
        return False
    if true_count == 1 and unknown_count == 0:
        return True
    if true_count == 0 and unknown_count == 0:
        return False
    return None
