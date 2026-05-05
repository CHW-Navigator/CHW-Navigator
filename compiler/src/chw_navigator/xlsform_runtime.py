from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .form_ir import XLSFormWorkbook


class XLSFormRuntimeError(Exception):
    """Raised when the generated XLSForm runtime cannot evaluate a workbook."""


@dataclass(slots=True)
class XLSFormEvaluationResult:
    values: dict[str, Any]
    visible_notes: list[str]


def evaluate_workbook(workbook: XLSFormWorkbook, patient_values: dict[str, Any]) -> XLSFormEvaluationResult:
    context = {
        row.name: patient_values.get(row.name)
        for row in workbook.survey
        if row.type not in {"calculate", "note"}
    }
    context.update(patient_values)
    visible_notes: list[str] = []

    for row in workbook.survey:
        if row.type == "note":
            is_visible = True if not row.relevant else _truthy(_Parser(row.relevant, context).parse())
            if is_visible:
                visible_notes.append(row.name)
            continue
        if row.type == "calculate":
            if not row.calculation:
                continue
            context[row.name] = _Parser(row.calculation, context).parse()
            continue

    return XLSFormEvaluationResult(values=context, visible_notes=visible_notes)


class _Parser:
    def __init__(self, text: str, context: dict[str, Any]) -> None:
        self.text = text
        self.context = context
        self.pos = 0

    def parse(self) -> Any:
        value = self._parse_or()
        self._skip_ws()
        if self.pos != len(self.text):
            raise XLSFormRuntimeError(f"unexpected trailing input at position {self.pos}")
        return value

    def _parse_or(self) -> Any:
        value = self._parse_and()
        while True:
            self._skip_ws()
            if self._match_keyword("or"):
                rhs = self._parse_and()
                value = _tri_or(value, rhs)
                continue
            return value

    def _parse_and(self) -> Any:
        value = self._parse_comparison()
        while True:
            self._skip_ws()
            if self._match_keyword("and"):
                rhs = self._parse_comparison()
                value = _tri_and(value, rhs)
                continue
            return value

    def _parse_comparison(self) -> Any:
        value = self._parse_additive()
        while True:
            self._skip_ws()
            operator = None
            for candidate in ("!=", "<=", ">=", "=", "<", ">"):
                if self.text.startswith(candidate, self.pos):
                    operator = candidate
                    self.pos += len(candidate)
                    break
            if operator is None:
                return value
            rhs = self._parse_additive()
            value = _compare_values(value, rhs, operator)

    def _parse_additive(self) -> Any:
        value = self._parse_multiplicative()
        while True:
            self._skip_ws()
            if self._peek("+"):
                self.pos += 1
                value = _apply_arithmetic(value, self._parse_multiplicative(), "+")
                continue
            if self._peek("-"):
                self.pos += 1
                value = _apply_arithmetic(value, self._parse_multiplicative(), "-")
                continue
            return value

    def _parse_multiplicative(self) -> Any:
        value = self._parse_unary()
        while True:
            self._skip_ws()
            if self._peek("*"):
                self.pos += 1
                value = _apply_arithmetic(value, self._parse_unary(), "*")
                continue
            if self._peek("/"):
                self.pos += 1
                value = _apply_arithmetic(value, self._parse_unary(), "/")
                continue
            return value

    def _parse_unary(self) -> Any:
        self._skip_ws()
        if self._match_keyword("not"):
            self._expect("(")
            value = self._parse_or()
            self._expect(")")
            return _tri_not(value)
        return self._parse_primary()

    def _parse_primary(self) -> Any:
        self._skip_ws()
        if self._peek("("):
            self.pos += 1
            value = self._parse_or()
            self._expect(")")
            return value
        if self._peek("${"):
            return self._parse_reference()
        if self.text.startswith("if(", self.pos):
            return self._parse_if()
        if self.text.startswith("selected(", self.pos):
            return self._parse_selected()
        if self.text.startswith("true()", self.pos):
            self.pos += len("true()")
            return True
        if self.text.startswith("false()", self.pos):
            self.pos += len("false()")
            return False
        if self._peek("'"):
            return self._parse_string()
        return self._parse_number()

    def _parse_reference(self) -> Any:
        self._expect("${")
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] != "}":
            self.pos += 1
        if self.pos >= len(self.text):
            raise XLSFormRuntimeError("unterminated ${ reference")
        name = self.text[start:self.pos]
        self._expect("}")
        if name not in self.context:
            raise XLSFormRuntimeError(f"unknown reference '{name}'")
        return self.context[name]

    def _parse_if(self) -> Any:
        self._expect("if(")
        cond = self._parse_or()
        self._expect(",")
        then_value = self._parse_or()
        self._expect(",")
        else_value = self._parse_or()
        self._expect(")")
        return then_value if _truthy(cond) else else_value

    def _parse_selected(self) -> Any:
        self._expect("selected(")
        target = self._parse_or()
        self._expect(",")
        choice = self._parse_or()
        self._expect(")")
        if target is None:
            return None
        if isinstance(target, str):
            return str(choice) in target.split()
        if isinstance(target, (list, tuple, set)):
            return choice in target
        return False

    def _parse_string(self) -> str:
        self._expect("'")
        chars: list[str] = []
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if char == "'":
                self.pos += 1
                return "".join(chars)
            if char == "\\" and self.pos + 1 < len(self.text):
                self.pos += 1
                chars.append(self.text[self.pos])
                self.pos += 1
                continue
            chars.append(char)
            self.pos += 1
        raise XLSFormRuntimeError("unterminated string literal")

    def _parse_number(self) -> Any:
        self._skip_ws()
        start = self.pos
        if self._peek("-"):
            self.pos += 1
        while self.pos < len(self.text) and self.text[self.pos].isdigit():
            self.pos += 1
        if self.pos < len(self.text) and self.text[self.pos] == ".":
            self.pos += 1
            while self.pos < len(self.text) and self.text[self.pos].isdigit():
                self.pos += 1
            return float(self.text[start:self.pos])
        token = self.text[start:self.pos]
        if not token:
            raise XLSFormRuntimeError(f"expected literal at position {self.pos}")
        return int(token)

    def _skip_ws(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def _peek(self, token: str) -> bool:
        return self.text.startswith(token, self.pos)

    def _match_keyword(self, token: str) -> bool:
        self._skip_ws()
        end = self.pos + len(token)
        if self.text[self.pos:end] != token:
            return False
        before_ok = self.pos == 0 or not self.text[self.pos - 1].isalnum()
        after_ok = end >= len(self.text) or not self.text[end].isalnum()
        if before_ok and after_ok:
            self.pos = end
            return True
        return False

    def _expect(self, token: str) -> None:
        self._skip_ws()
        if not self.text.startswith(token, self.pos):
            raise XLSFormRuntimeError(f"expected '{token}' at position {self.pos}")
        self.pos += len(token)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    return bool(value)


def _tri_not(value: Any) -> bool | None:
    if value is None:
        return None
    return not _truthy(value)


def _tri_and(left: Any, right: Any) -> bool | None:
    left_bool = _coerce_bool(left)
    right_bool = _coerce_bool(right)
    if left_bool is False or right_bool is False:
        return False
    if left_bool is None or right_bool is None:
        return None
    return True


def _tri_or(left: Any, right: Any) -> bool | None:
    left_bool = _coerce_bool(left)
    right_bool = _coerce_bool(right)
    if left_bool is True or right_bool is True:
        return True
    if left_bool is None or right_bool is None:
        return None
    return False


def _coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    return bool(value)


def _compare_values(left: Any, right: Any, operator: str) -> bool | None:
    if left is None or right is None:
        return None
    try:
        if operator == "=":
            return left == right
        if operator == "!=":
            return left != right
        if operator == "<":
            return left < right
        if operator == "<=":
            return left <= right
        if operator == ">":
            return left > right
        if operator == ">=":
            return left >= right
    except TypeError as exc:
        raise XLSFormRuntimeError(
            f"comparison '{operator}' is not valid for values {left!r} and {right!r}"
        ) from exc
    raise XLSFormRuntimeError(f"unsupported comparison operator '{operator}'")


def _apply_arithmetic(left: Any, right: Any, operator: str) -> Any:
    if left is None or right is None:
        return None
    try:
        if operator == "+":
            return left + right
        if operator == "-":
            return left - right
        if operator == "*":
            return left * right
        if operator == "/":
            return left / right
    except ZeroDivisionError as exc:
        raise XLSFormRuntimeError(
            f"division by zero while evaluating arithmetic expression with values {left!r} and {right!r}"
        ) from exc
    except TypeError as exc:
        raise XLSFormRuntimeError(
            f"arithmetic operator '{operator}' is not valid for values {left!r} and {right!r}"
        ) from exc
    raise XLSFormRuntimeError(f"unsupported arithmetic operator '{operator}'")
