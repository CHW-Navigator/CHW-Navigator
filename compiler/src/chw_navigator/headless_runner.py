from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .form_ir import XLSFormWorkbook


class HeadlessRunnerError(Exception):
    """Raised when the headless XLSForm runner cannot evaluate a workbook."""


@dataclass(slots=True)
class HeadlessEvaluationResult:
    values: dict[str, Any]
    visible_notes: list[str]


@dataclass(slots=True)
class _Token:
    kind: str
    value: Any


def evaluate_workbook_headless(workbook: XLSFormWorkbook, patient_values: dict[str, Any]) -> HeadlessEvaluationResult:
    context = {
        row.name: patient_values.get(row.name)
        for row in workbook.survey
        if row.type not in {"calculate", "note"}
    }
    context.update(patient_values)
    visible_notes: list[str] = []

    for row in workbook.survey:
        if row.type == "note":
            visible = True
            if row.relevant:
                visible = _coerce_truth(_ExpressionEngine(row.relevant, context).evaluate())
            if visible:
                visible_notes.append(row.name)
            continue
        if row.type == "calculate":
            if not row.calculation:
                continue
            context[row.name] = _ExpressionEngine(row.calculation, context).evaluate()
            continue

    return HeadlessEvaluationResult(values=context, visible_notes=visible_notes)


class _ExpressionEngine:
    def __init__(self, text: str, context: dict[str, Any]) -> None:
        self.context = context
        self.tokens = _Tokenizer(text).tokens()
        self.index = 0

    def evaluate(self) -> Any:
        value = self._parse_or()
        self._expect("EOF")
        return value

    def _parse_or(self) -> Any:
        value = self._parse_and()
        while self._match("OR"):
            rhs = self._parse_and()
            value = _tri_or(value, rhs)
        return value

    def _parse_and(self) -> Any:
        value = self._parse_comparison()
        while self._match("AND"):
            rhs = self._parse_comparison()
            value = _tri_and(value, rhs)
        return value

    def _parse_comparison(self) -> Any:
        value = self._parse_additive()
        while self._peek().kind in {"EQ", "NE", "LT", "LE", "GT", "GE"}:
            operator = self._advance().value
            rhs = self._parse_additive()
            value = _compare_values(value, rhs, operator)
        return value

    def _parse_additive(self) -> Any:
        value = self._parse_multiplicative()
        while self._peek().kind in {"PLUS", "MINUS"}:
            operator = self._advance().value
            rhs = self._parse_multiplicative()
            value = _apply_arithmetic(value, rhs, operator)
        return value

    def _parse_multiplicative(self) -> Any:
        value = self._parse_unary()
        while self._peek().kind in {"STAR", "SLASH"}:
            operator = self._advance().value
            rhs = self._parse_unary()
            value = _apply_arithmetic(value, rhs, operator)
        return value

    def _parse_unary(self) -> Any:
        if self._match("NOT"):
            value = self._parse_unary()
            return _tri_not(value)
        if self._match("MINUS"):
            value = self._parse_unary()
            if value is None:
                return None
            if not isinstance(value, (int, float)):
                raise HeadlessRunnerError(f"cannot negate non-numeric value {value!r}")
            return -value
        return self._parse_primary()

    def _parse_primary(self) -> Any:
        token = self._peek()
        if self._match("LPAREN"):
            value = self._parse_or()
            self._expect("RPAREN")
            return value
        if self._match("TRUE"):
            return True
        if self._match("FALSE"):
            return False
        if token.kind == "REF":
            self._advance()
            if token.value not in self.context:
                raise HeadlessRunnerError(f"unknown reference '{token.value}'")
            return self.context[token.value]
        if token.kind == "NUMBER":
            self._advance()
            return token.value
        if token.kind == "STRING":
            self._advance()
            return token.value
        if token.kind == "IDENT":
            if token.value == "if":
                return self._parse_if_call()
            if token.value == "selected":
                return self._parse_selected_call()
        raise HeadlessRunnerError(f"unexpected token '{token.kind}'")

    def _parse_if_call(self) -> Any:
        self._expect("IDENT", "if")
        self._expect("LPAREN")
        cond = self._parse_or()
        self._expect("COMMA")
        then_value = self._parse_or()
        self._expect("COMMA")
        else_value = self._parse_or()
        self._expect("RPAREN")
        return then_value if _coerce_truth(cond) else else_value

    def _parse_selected_call(self) -> Any:
        self._expect("IDENT", "selected")
        self._expect("LPAREN")
        target = self._parse_or()
        self._expect("COMMA")
        choice = self._parse_or()
        self._expect("RPAREN")
        if target is None:
            return None
        if isinstance(target, str):
            return str(choice) in target.split()
        if isinstance(target, (list, tuple, set)):
            return choice in target
        return False

    def _peek(self) -> _Token:
        return self.tokens[self.index]

    def _advance(self) -> _Token:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def _match(self, kind: str) -> bool:
        if self._peek().kind != kind:
            return False
        self.index += 1
        return True

    def _expect(self, kind: str, value: Any | None = None) -> _Token:
        token = self._peek()
        if token.kind != kind:
            raise HeadlessRunnerError(f"expected token '{kind}', found '{token.kind}'")
        if value is not None and token.value != value:
            raise HeadlessRunnerError(f"expected token value {value!r}, found {token.value!r}")
        self.index += 1
        return token


class _Tokenizer:
    def __init__(self, text: str) -> None:
        self.text = text
        self.index = 0

    def tokens(self) -> list[_Token]:
        items: list[_Token] = []
        while self.index < len(self.text):
            char = self.text[self.index]
            if char.isspace():
                self.index += 1
                continue
            if self.text.startswith("${", self.index):
                items.append(_Token("REF", self._read_reference()))
                continue
            if char == "'":
                items.append(_Token("STRING", self._read_string()))
                continue
            if char.isdigit() or (char == "-" and self._next_is_digit()):
                items.append(_Token("NUMBER", self._read_number()))
                continue
            if char.isalpha() or char == "_":
                items.append(self._read_identifier())
                continue
            if self.text.startswith("!=", self.index):
                self.index += 2
                items.append(_Token("NE", "!="))
                continue
            if self.text.startswith("<=", self.index):
                self.index += 2
                items.append(_Token("LE", "<="))
                continue
            if self.text.startswith(">=", self.index):
                self.index += 2
                items.append(_Token("GE", ">="))
                continue
            single_tokens = {
                "=": ("EQ", "="),
                "<": ("LT", "<"),
                ">": ("GT", ">"),
                "+": ("PLUS", "+"),
                "-": ("MINUS", "-"),
                "*": ("STAR", "*"),
                "/": ("SLASH", "/"),
                "(": ("LPAREN", "("),
                ")": ("RPAREN", ")"),
                ",": ("COMMA", ","),
            }
            if char in single_tokens:
                self.index += 1
                kind, value = single_tokens[char]
                items.append(_Token(kind, value))
                continue
            raise HeadlessRunnerError(f"unexpected character '{char}' at position {self.index}")
        items.append(_Token("EOF", None))
        return items

    def _read_reference(self) -> str:
        self.index += 2
        start = self.index
        while self.index < len(self.text) and self.text[self.index] != "}":
            self.index += 1
        if self.index >= len(self.text):
            raise HeadlessRunnerError("unterminated ${ reference")
        value = self.text[start:self.index]
        self.index += 1
        return value

    def _read_string(self) -> str:
        self.index += 1
        chars: list[str] = []
        while self.index < len(self.text):
            char = self.text[self.index]
            if char == "'":
                self.index += 1
                return "".join(chars)
            if char == "\\" and self.index + 1 < len(self.text):
                self.index += 1
                chars.append(self.text[self.index])
                self.index += 1
                continue
            chars.append(char)
            self.index += 1
        raise HeadlessRunnerError("unterminated string literal")

    def _read_number(self) -> int | float:
        start = self.index
        if self.text[self.index] == "-":
            self.index += 1
        while self.index < len(self.text) and self.text[self.index].isdigit():
            self.index += 1
        if self.index < len(self.text) and self.text[self.index] == ".":
            self.index += 1
            while self.index < len(self.text) and self.text[self.index].isdigit():
                self.index += 1
            return float(self.text[start:self.index])
        return int(self.text[start:self.index])

    def _read_identifier(self) -> _Token:
        start = self.index
        while self.index < len(self.text) and (self.text[self.index].isalnum() or self.text[self.index] == "_"):
            self.index += 1
        value = self.text[start:self.index]
        if value == "and":
            return _Token("AND", value)
        if value == "or":
            return _Token("OR", value)
        if value == "not":
            return _Token("NOT", value)
        if value == "true" and self.text.startswith("()", self.index):
            self.index += 2
            return _Token("TRUE", True)
        if value == "false" and self.text.startswith("()", self.index):
            self.index += 2
            return _Token("FALSE", False)
        return _Token("IDENT", value)

    def _next_is_digit(self) -> bool:
        return self.index + 1 < len(self.text) and self.text[self.index + 1].isdigit()


def _coerce_truth(value: Any) -> bool:
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
    return not _coerce_truth(value)


def _tri_and(left: Any, right: Any) -> bool | None:
    left_bool = _coerce_optional_bool(left)
    right_bool = _coerce_optional_bool(right)
    if left_bool is False or right_bool is False:
        return False
    if left_bool is None or right_bool is None:
        return None
    return True


def _tri_or(left: Any, right: Any) -> bool | None:
    left_bool = _coerce_optional_bool(left)
    right_bool = _coerce_optional_bool(right)
    if left_bool is True or right_bool is True:
        return True
    if left_bool is None or right_bool is None:
        return None
    return False


def _coerce_optional_bool(value: Any) -> bool | None:
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
        raise HeadlessRunnerError(
            f"comparison '{operator}' is not valid for values {left!r} and {right!r}"
        ) from exc
    raise HeadlessRunnerError(f"unsupported comparison operator '{operator}'")


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
        raise HeadlessRunnerError(
            f"division by zero while evaluating arithmetic expression with values {left!r} and {right!r}"
        ) from exc
    except TypeError as exc:
        raise HeadlessRunnerError(
            f"arithmetic operator '{operator}' is not valid for values {left!r} and {right!r}"
        ) from exc
    raise HeadlessRunnerError(f"unsupported arithmetic operator '{operator}'")
