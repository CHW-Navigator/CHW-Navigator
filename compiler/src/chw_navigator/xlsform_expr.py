from __future__ import annotations

from typing import Any


class XLSFormExpressionError(Exception):
    """Raised when an XLSForm expression cannot be parsed into the supported AST subset."""


def parse_xlsform_expression(text: str) -> dict[str, Any]:
    parser = _ExpressionParser(text)
    return parser.parse()


class _ExpressionParser:
    def __init__(self, text: str) -> None:
        self.text = text.strip()
        self.pos = 0

    def parse(self) -> dict[str, Any]:
        value = self._parse_or()
        self._skip_ws()
        if self.pos != len(self.text):
            raise XLSFormExpressionError(f"unexpected trailing input at position {self.pos}")
        return value

    def _parse_or(self) -> dict[str, Any]:
        value = self._parse_and()
        while True:
            self._skip_ws()
            if self._match_keyword("or"):
                rhs = self._parse_and()
                value = _join_variadic("or", value, rhs)
                continue
            return value

    def _parse_and(self) -> dict[str, Any]:
        value = self._parse_comparison()
        while True:
            self._skip_ws()
            if self._match_keyword("and"):
                rhs = self._parse_comparison()
                value = _join_variadic("and", value, rhs)
                continue
            return value

    def _parse_comparison(self) -> dict[str, Any]:
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
            value = {"kind": operator, "left": value, "right": rhs}

    def _parse_additive(self) -> dict[str, Any]:
        value = self._parse_multiplicative()
        while True:
            self._skip_ws()
            if self._peek("+"):
                self.pos += 1
                value = {"kind": "+", "left": value, "right": self._parse_multiplicative()}
                continue
            if self._peek("-"):
                self.pos += 1
                value = {"kind": "-", "left": value, "right": self._parse_multiplicative()}
                continue
            return value

    def _parse_multiplicative(self) -> dict[str, Any]:
        value = self._parse_unary()
        while True:
            self._skip_ws()
            if self._peek("*"):
                self.pos += 1
                value = {"kind": "*", "left": value, "right": self._parse_unary()}
                continue
            if self._peek("/"):
                self.pos += 1
                value = {"kind": "/", "left": value, "right": self._parse_unary()}
                continue
            return value

    def _parse_unary(self) -> dict[str, Any]:
        self._skip_ws()
        if self._match_keyword("not"):
            self._expect("(")
            value = self._parse_or()
            self._expect(")")
            return {"kind": "not", "arg": value}
        return self._parse_primary()

    def _parse_primary(self) -> dict[str, Any]:
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
            return {"kind": "literal", "value": True}
        if self.text.startswith("false()", self.pos):
            self.pos += len("false()")
            return {"kind": "literal", "value": False}
        if self._peek("'"):
            return {"kind": "literal", "value": self._parse_string()}
        return {"kind": "literal", "value": self._parse_number()}

    def _parse_reference(self) -> dict[str, Any]:
        self._expect("${")
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] != "}":
            self.pos += 1
        if self.pos >= len(self.text):
            raise XLSFormExpressionError("unterminated ${ reference")
        name = self.text[start:self.pos]
        self._expect("}")
        return {"kind": "ref", "id": name}

    def _parse_if(self) -> dict[str, Any]:
        self._expect("if(")
        cond = self._parse_or()
        self._expect(",")
        then_expr = self._parse_or()
        self._expect(",")
        else_expr = self._parse_or()
        self._expect(")")
        return {"kind": "if", "cond": cond, "then": then_expr, "else": else_expr}

    def _parse_selected(self) -> dict[str, Any]:
        self._expect("selected(")
        target = self._parse_or()
        self._expect(",")
        choice = self._parse_or()
        self._expect(")")
        if choice.get("kind") != "literal" or not isinstance(choice.get("value"), str):
            raise XLSFormExpressionError("selected() choice must be a string literal")
        return {"kind": "selected", "target": target, "choice": choice["value"]}

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
        raise XLSFormExpressionError("unterminated string literal")

    def _parse_number(self) -> int | float:
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
            token = self.text[start:self.pos]
            if not token or token == "-":
                raise XLSFormExpressionError(f"expected number at position {start}")
            return float(token)
        token = self.text[start:self.pos]
        if not token or token == "-":
            raise XLSFormExpressionError(f"expected literal at position {self.pos}")
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
            raise XLSFormExpressionError(f"expected '{token}' at position {self.pos}")
        self.pos += len(token)


def _join_variadic(kind: str, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    args: list[dict[str, Any]] = []
    if left.get("kind") == kind:
        args.extend(left["args"])
    else:
        args.append(left)
    if right.get("kind") == kind:
        args.extend(right["args"])
    else:
        args.append(right)
    return {"kind": kind, "args": args}
