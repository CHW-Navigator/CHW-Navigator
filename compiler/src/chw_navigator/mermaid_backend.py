from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass, field
from typing import Any

from .clinical_ir import ClinicalIRDocument


@dataclass(slots=True)
class MermaidArtifact:
    text: str
    node_sources: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


@dataclass(slots=True)
class MermaidOptions:
    direction: str = "LR"
    font_size_px: int = 24
    font_family: str = "Arial, Helvetica, sans-serif"
    line_height: float = 1.3
    curve: str = "basis"


@dataclass(slots=True)
class MermaidComparisonResult:
    ok: bool
    mismatches: list[str] = field(default_factory=list)


def build_mermaid_artifact(document: ClinicalIRDocument, options: MermaidOptions | None = None) -> MermaidArtifact:
    opts = options or MermaidOptions()
    lines: list[str] = [_init_directive(opts), f"flowchart {opts.direction}"]
    node_sources: dict[str, list[dict[str, Any]]] = {}

    for variable_id, variable in document.variables.items():
        lines.append(f'  {variable_id}["{_node_label(variable_id, variable_id)}"]')
        lines.append(f"  class {variable_id} variable")
        node_sources[variable_id] = _provenance_dicts(variable.provenance)

    for predicate_id, predicate in document.predicates.items():
        lines.append(f'  {predicate_id}{{"{_node_label(predicate_id, predicate_id)}"}}')
        lines.append(f"  class {predicate_id} predicate")
        node_sources[predicate_id] = _provenance_dicts(predicate.provenance)

    for decision_id, decision in document.decisions.items():
        lines.append(f'  {decision_id}{{{{"{_node_label(decision_id, decision_id)}"}}}}')
        lines.append(f"  class {decision_id} decision")
        node_sources[decision_id] = _provenance_dicts(decision.provenance)

    for output_id, output in document.outputs.items():
        lines.append(f'  {output_id}["{_node_label(output_id, output_id)}"]')
        lines.append(f"  class {output_id} output")
        node_sources[output_id] = _provenance_dicts(output.provenance)

    for predicate_id, predicate in document.predicates.items():
        for input_id in predicate.inputs_used:
            lines.append(f"  {input_id} --> {predicate_id}")

    for decision_id, decision in document.decisions.items():
        previous_rule_node: str | None = None
        for index, rule in enumerate(decision.rules, start=1):
            rule_node = f"{decision_id}__{rule.id}"
            lines.append(f'  {rule_node}["{_rule_label(rule)}"]')
            lines.append(f"  class {rule_node} rule")
            node_sources[rule_node] = _merge_provenance(decision.provenance, rule.provenance)
            if previous_rule_node is None:
                lines.append(f"  {decision_id} -->|priority {index}| {rule_node}")
            else:
                lines.append(f"  {previous_rule_node} -->|else next| {rule_node}")
            previous_rule_node = rule_node

            for ref in sorted(_collect_refs(rule.when)):
                if ref in document.variables or ref in document.predicates or ref in document.outputs:
                    lines.append(f"  {ref} -.-> {rule_node}")

            for output_id, value in rule.then.items():
                lines.append(f'  {rule_node} -->|{output_id}={_literal_label(value)}| {output_id}')

    lines.extend(_class_defs(opts))
    return MermaidArtifact(text="\n".join(lines) + "\n", node_sources=node_sources)


def build_mermaid(document: ClinicalIRDocument, options: MermaidOptions | None = None) -> str:
    return build_mermaid_artifact(document, options=options).text


def compare_mermaid_text(document: ClinicalIRDocument, candidate_text: str) -> MermaidComparisonResult:
    expected_lines = _normalized_lines(build_mermaid_artifact(document).text)
    actual_lines = _normalized_lines(candidate_text)
    mismatches: list[str] = []

    missing = sorted(expected_lines - actual_lines)
    unexpected = sorted(actual_lines - expected_lines)
    if missing:
        mismatches.extend(f"missing mermaid line: {line}" for line in missing)
    if unexpected:
        mismatches.extend(f"unexpected mermaid line: {line}" for line in unexpected)
    return MermaidComparisonResult(ok=not mismatches, mismatches=mismatches)


def _collect_refs(expr: dict[str, Any]) -> set[str]:
    kind = expr.get("kind")
    if kind in {"var", "pred", "output"} and "id" in expr:
        return {str(expr["id"])}
    if kind in {"literal", "const", "else"}:
        return set()
    if kind in {"and", "or", "exactly_one"}:
        refs: set[str] = set()
        for arg in expr.get("args", []):
            refs |= _collect_refs(arg)
        return refs
    if kind == "not":
        arg = expr.get("arg")
        return _collect_refs(arg) if isinstance(arg, dict) else set()
    if kind == "if":
        refs: set[str] = set()
        for key in ("cond", "then", "else"):
            value = expr.get(key)
            if isinstance(value, dict):
                refs |= _collect_refs(value)
        return refs
    if kind in {"=", "!=", "<", "<=", ">", ">=", "+", "-", "*", "/"}:
        refs: set[str] = set()
        left = expr.get("left")
        right = expr.get("right")
        if isinstance(left, dict):
            refs |= _collect_refs(left)
        if isinstance(right, dict):
            refs |= _collect_refs(right)
        return refs
    if kind == "selected":
        target = expr.get("target")
        return _collect_refs(target) if isinstance(target, dict) else set()
    return set()


def _expr_summary(expr: dict[str, Any]) -> str:
    kind = expr.get("kind")
    if kind == "else":
        return "else"
    if kind in {"var", "pred", "output"}:
        return _humanize_identifier(str(expr.get("id")))
    if kind == "literal":
        return _literal_label(expr.get("value"))
    if kind == "not":
        return f"not({_expr_summary(expr['arg'])})"
    if kind in {"and", "or"}:
        joiner = f" {kind} "
        return joiner.join(_expr_summary(arg) for arg in expr.get("args", []))
    if kind in {"=", "!=", "<", "<=", ">", ">=", "+", "-", "*", "/"}:
        return f"{_expr_summary(expr['left'])} {kind} {_expr_summary(expr['right'])}"
    return str(kind or "expr")


def _node_label(identifier: str, fallback: str) -> str:
    pretty = _humanize_identifier(identifier) or fallback
    return _wrap_label(pretty, width=18)


def _rule_label(rule) -> str:
    head = _humanize_identifier(rule.id)
    tail = _expr_summary(rule.when)
    return _wrap_label(f"{head}: {tail}", width=26)


def _wrap_label(text: str, width: int) -> str:
    chunks = textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)
    return "<br/>".join(chunks or [text])


def _humanize_identifier(identifier: str) -> str:
    text = identifier
    for prefix in ("v_", "p_", "d_", "o_", "r_", "c_", "st_", "h_"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    text = text.replace("__", " ").replace("_", " ")
    text = text.replace(" dx ", " diagnosis ").replace(" rx ", " treatment ").replace(" fu ", " follow up ")
    text = " ".join(text.split())
    if not text:
        return identifier
    return text[0].upper() + text[1:]


def _literal_label(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _init_directive(options: MermaidOptions) -> str:
    payload = {
        "theme": "base",
        "flowchart": {
            "curve": options.curve,
            "htmlLabels": True,
            "nodeSpacing": 40,
            "rankSpacing": 52,
        },
        "themeVariables": {
            "fontFamily": options.font_family,
            "fontSize": f"{options.font_size_px}px",
            "lineColor": "#355070",
            "primaryTextColor": "#16324f",
            "secondaryTextColor": "#16324f",
            "tertiaryTextColor": "#16324f",
        },
    }
    return f"%%{{init: {json.dumps(payload, separators=(',', ':'))}}}%%"


def _class_defs(options: MermaidOptions) -> list[str]:
    shared = f"color:#16324f,font-size:{options.font_size_px}px,font-family:{options.font_family},stroke-width:2px;"
    return [
        f"  classDef variable fill:#eef6fb,stroke:#355070,{shared}",
        f"  classDef predicate fill:#fff4db,stroke:#355070,{shared}",
        f"  classDef decision fill:#dfeaf7,stroke:#16324f,{shared}",
        f"  classDef output fill:#d7efe8,stroke:#2a9d8f,{shared}",
        f"  classDef rule fill:#fff1eb,stroke:#e76f51,{shared}",
        f"  linkStyle default stroke:#355070,stroke-width:2px;",
    ]


def _provenance_dicts(records) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


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


def _normalized_lines(text: str) -> set[str]:
    return {
        line.strip()
        for line in text.splitlines()
        if line.strip()
    }
