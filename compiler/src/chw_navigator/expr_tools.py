from __future__ import annotations

from typing import Any, Iterable


def iter_child_exprs(expr: dict[str, Any]) -> Iterable[dict[str, Any]]:
    kind = expr.get("kind")
    if kind == "call":
        for arg in expr.get("args", []):
            if isinstance(arg, dict):
                yield arg
        return
    if kind in {"and", "or", "exactly_one"}:
        for arg in expr.get("args", []):
            if isinstance(arg, dict):
                yield arg
        return
    if kind == "not":
        arg = expr.get("arg")
        if isinstance(arg, dict):
            yield arg
        return
    if kind == "if":
        for key in ("cond", "then", "else"):
            value = expr.get(key)
            if isinstance(value, dict):
                yield value
        return
    if kind in {"=", "!=", "<", "<=", ">", ">=", "+", "-", "*", "/"}:
        left = expr.get("left")
        right = expr.get("right")
        if isinstance(left, dict):
            yield left
        if isinstance(right, dict):
            yield right
        return
    if kind == "selected":
        target = expr.get("target")
        if isinstance(target, dict):
            yield target


def collect_refs(expr: dict[str, Any], kinds: set[str]) -> set[str]:
    kind = expr.get("kind")
    refs: set[str] = set()
    if kind in kinds and "id" in expr:
        refs.add(str(expr["id"]))
    for child in iter_child_exprs(expr):
        refs |= collect_refs(child, kinds)
    return refs


def is_else_expr(expr: dict[str, Any]) -> bool:
    return expr.get("kind") == "else"
