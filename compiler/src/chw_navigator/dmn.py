from __future__ import annotations

import copy
import re
from typing import Any

import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException

from .clinical_ir import ClinicalIRDocument, DecisionDef, HitPolicy, OutputDef, ProvenanceRecord, RuleDef, ScalarType
from .validator import validate_document


class DMNImportError(Exception):
    """Raised when a DMN file uses unsupported constructs."""


def lint_dmn_file(dmn_path: str) -> dict[str, Any]:
    root = _parse_dmn_root(dmn_path)
    decision_count = 0
    rule_count = 0
    output_count = 0
    issues: list[dict[str, str]] = []
    for decision_elem in _children_by_name(root, "decision"):
        decision_count += 1
        decision_summary = _lint_decision(decision_elem, dmn_path)
        rule_count += int(decision_summary["rule_count"])
        output_count += int(decision_summary["output_count"])
        issues.extend(decision_summary["issues"])
    if decision_count == 0:
        issues.append(
            {
                "level": "ERROR",
                "path": "dmn",
                "message": "DMN file does not contain any supported decision elements",
            }
        )
    return {
        "ok": not any(item["level"] == "ERROR" for item in issues),
        "decision_count": decision_count,
        "rule_count": rule_count,
        "output_count": output_count,
        "issues": issues,
    }


def import_dmn_decisions(
    base_document: ClinicalIRDocument,
    dmn_path: str,
) -> ClinicalIRDocument:
    root = _parse_dmn_root(dmn_path)
    decisions = copy.deepcopy(base_document.decisions)
    outputs = copy.deepcopy(base_document.outputs)

    for decision_elem in _children_by_name(root, "decision"):
        decision, inferred_outputs = _parse_decision(decision_elem, dmn_path)
        decisions[decision.id] = decision
        for output_id, output_def in inferred_outputs.items():
            existing = outputs.get(output_id)
            if existing is not None:
                if existing.type is not output_def.type:
                    raise DMNImportError(
                        f"DMN output '{output_id}' inferred type '{output_def.type}' conflicts with existing output type '{existing.type}'"
                    )
                continue
            outputs[output_id] = output_def

    merged = copy.deepcopy(base_document)
    merged.decisions = decisions
    merged.outputs = outputs
    validation_errors = validate_document(merged)
    if validation_errors:
        message = "; ".join(f"{item.path}: {item.message}" for item in validation_errors)
        raise DMNImportError(f"imported DMN does not satisfy the supported Clinical IR subset: {message}")
    return merged


def _parse_dmn_root(dmn_path: str) -> ET.Element:
    try:
        return ET.parse(dmn_path).getroot()
    except FileNotFoundError as exc:
        raise DMNImportError(f"DMN file not found: {dmn_path}") from exc
    except (OSError, ET.ParseError, DefusedXmlException) as exc:
        raise DMNImportError(f"unsafe or invalid DMN XML in '{dmn_path}': {exc}") from exc


def _lint_decision(decision_elem: ET.Element, source_id: str) -> dict[str, Any]:
    decision_id = decision_elem.attrib.get("id") or _slug_to_identifier(
        decision_elem.attrib.get("name", "decision"), "d"
    )
    issues: list[dict[str, str]] = []
    table = _first_child_by_name(decision_elem, "decisionTable")
    if table is None:
        issues.append(
            {
                "level": "ERROR",
                "path": f"dmn.decision.{decision_id}",
                "message": "decision is missing a decisionTable",
            }
        )
        return {"rule_count": 0, "output_count": 0, "issues": issues}

    hit_policy = table.attrib.get("hitPolicy", "FIRST")
    if hit_policy != "FIRST":
        issues.append(
            {
                "level": "ERROR",
                "path": f"dmn.decision.{decision_id}.hitPolicy",
                "message": f"unsupported hit policy '{hit_policy}'; DMN v1 supports FIRST only",
            }
        )

    inputs = _children_by_name(table, "input")
    outputs = _children_by_name(table, "output")
    rules = _children_by_name(table, "rule")

    if not inputs:
        issues.append(
            {
                "level": "ERROR",
                "path": f"dmn.decision.{decision_id}.inputs",
                "message": "decision must define at least one input",
            }
        )
    if not outputs:
        issues.append(
            {
                "level": "ERROR",
                "path": f"dmn.decision.{decision_id}.outputs",
                "message": "decision must define at least one output",
            }
        )
    if not rules:
        issues.append(
            {
                "level": "ERROR",
                "path": f"dmn.decision.{decision_id}.rules",
                "message": "decision must define at least one rule",
            }
        )

    input_refs = [_lint_input_ref(decision_id, item, issues) for item in inputs]
    output_refs = [_lint_output_ref(decision_id, item, issues) for item in outputs]

    seen_rule_ids: set[str] = set()
    seen_patterns: dict[tuple[str, ...], str] = {}
    for index, rule_elem in enumerate(rules, start=1):
        rule_id = rule_elem.attrib.get("id") or f"{decision_id}_r{index}"
        if rule_id in seen_rule_ids:
            issues.append(
                {
                    "level": "ERROR",
                    "path": f"dmn.decision.{decision_id}.rule.{rule_id}",
                    "message": f"duplicate rule id '{rule_id}'",
                }
            )
        seen_rule_ids.add(rule_id)

        input_entries = _children_by_name(rule_elem, "inputEntry")
        output_entries = _children_by_name(rule_elem, "outputEntry")
        if input_refs and len(input_entries) != len(input_refs):
            issues.append(
                {
                    "level": "ERROR",
                    "path": f"dmn.decision.{decision_id}.rule.{rule_id}.inputs",
                    "message": f"rule has {len(input_entries)} input entries but expected {len(input_refs)}",
                }
            )
        if output_refs and len(output_entries) != len(output_refs):
            issues.append(
                {
                    "level": "ERROR",
                    "path": f"dmn.decision.{decision_id}.rule.{rule_id}.outputs",
                    "message": f"rule has {len(output_entries)} output entries but expected {len(output_refs)}",
                }
            )

        input_pattern = tuple(_text_from_cell(entry) for entry in input_entries)
        if input_pattern in seen_patterns:
            issues.append(
                {
                    "level": "WARNING",
                    "path": f"dmn.decision.{decision_id}.rule.{rule_id}",
                    "message": f"rule repeats the same input pattern as '{seen_patterns[input_pattern]}'",
                }
            )
        else:
            seen_patterns[input_pattern] = rule_id

        all_inputs_blank = True
        for ref, entry in zip(input_refs, input_entries, strict=False):
            cell_text = _text_from_cell(entry)
            all_inputs_blank = all_inputs_blank and cell_text in {"", "-"}
            _lint_input_cell(decision_id, rule_id, ref or "<missing_input>", cell_text, issues)

        has_output_assignment = False
        for ref, entry in zip(output_refs, output_entries, strict=False):
            cell_text = _text_from_cell(entry)
            if cell_text not in {"", "-", "\"\""}:
                has_output_assignment = True
            _lint_output_cell(decision_id, rule_id, ref or "<missing_output>", cell_text, issues)

        if not has_output_assignment:
            issues.append(
                {
                    "level": "ERROR",
                    "path": f"dmn.decision.{decision_id}.rule.{rule_id}",
                    "message": "rule row does not assign any outputs",
                }
            )
        if all_inputs_blank and not has_output_assignment:
            issues.append(
                {
                    "level": "ERROR",
                    "path": f"dmn.decision.{decision_id}.rule.{rule_id}",
                    "message": "rule row is empty; provide conditions, outputs, or remove the row",
                }
            )

    return {
        "rule_count": len(rules),
        "output_count": len(outputs),
        "issues": issues,
    }


def _parse_decision(decision_elem: ET.Element, source_id: str) -> tuple[DecisionDef, dict[str, OutputDef]]:
    decision_id = decision_elem.attrib.get("id") or _slug_to_identifier(
        decision_elem.attrib.get("name", "decision"), "d"
    )
    table = _first_child_by_name(decision_elem, "decisionTable")
    if table is None:
        raise DMNImportError(f"decision '{decision_id}' is missing a decisionTable")

    hit_policy = table.attrib.get("hitPolicy", "FIRST")
    if hit_policy != "FIRST":
        raise DMNImportError(f"decision '{decision_id}' uses unsupported hit policy '{hit_policy}'")

    inputs = _children_by_name(table, "input")
    outputs = _children_by_name(table, "output")
    rules = _children_by_name(table, "rule")

    if not inputs:
        raise DMNImportError(f"decision '{decision_id}' must define at least one input")
    if not outputs:
        raise DMNImportError(f"decision '{decision_id}' must define at least one output")
    if not rules:
        raise DMNImportError(f"decision '{decision_id}' must define at least one rule")

    input_refs = [_parse_input_ref(item) for item in inputs]
    output_refs = [_parse_output_ref(item) for item in outputs]

    parsed_rules = [
        _parse_rule(decision_id, input_refs, output_refs, rule, idx, source_id)
        for idx, rule in enumerate(rules)
    ]
    inferred_outputs = {
        output_id: _infer_output_def(decision_id, output_id, parsed_rules, source_id)
        for output_id in output_refs
    }

    return (
        DecisionDef(
            id=decision_id,
            hit_policy=HitPolicy.FIRST,
            rules=parsed_rules,
            provenance=[
                ProvenanceRecord(
                    source_id=source_id,
                    kind="dmn_decision",
                    location=f"decision:{decision_id}",
                )
            ],
        ),
        inferred_outputs,
    )


def _parse_rule(
    decision_id: str,
    input_refs: list[str],
    output_refs: list[str],
    rule_elem: ET.Element,
    index: int,
    source_id: str,
) -> RuleDef:
    input_entries = _children_by_name(rule_elem, "inputEntry")
    output_entries = _children_by_name(rule_elem, "outputEntry")

    if len(input_entries) != len(input_refs):
        raise DMNImportError(
            f"decision '{decision_id}' rule {index + 1} has {len(input_entries)} input entries but expected {len(input_refs)}"
        )
    if len(output_entries) != len(output_refs):
        raise DMNImportError(
            f"decision '{decision_id}' rule {index + 1} has {len(output_entries)} output entries but expected {len(output_refs)}"
        )

    conditions = [
        _parse_input_entry(input_ref, _text_from_cell(entry))
        for input_ref, entry in zip(input_refs, input_entries, strict=True)
    ]
    non_wildcards = [item for item in conditions if item is not None]
    when = {"kind": "else"} if not non_wildcards else _conjoin(non_wildcards)

    then: dict[str, Any] = {}
    for output_ref, output_entry in zip(output_refs, output_entries, strict=True):
        value_text = _text_from_cell(output_entry)
        if value_text in {"", "-", "\"\""}:
            continue
        then[output_ref] = _parse_scalar_text(value_text)

    return RuleDef(
        id=rule_elem.attrib.get("id") or f"{decision_id}_r{index + 1}",
        when=when,
        then=then,
        provenance=[
            ProvenanceRecord(
                source_id=source_id,
                kind="dmn_rule",
                location=f"decision:{decision_id}/rule:{rule_elem.attrib.get('id') or index + 1}",
                row=index + 1,
            )
        ],
    )


def _lint_input_ref(decision_id: str, input_elem: ET.Element, issues: list[dict[str, str]]) -> str | None:
    input_id = input_elem.attrib.get("id") or "input"
    input_expression = _first_child_by_name(input_elem, "inputExpression")
    if input_expression is None:
        issues.append(
            {
                "level": "ERROR",
                "path": f"dmn.decision.{decision_id}.input.{input_id}",
                "message": "input is missing inputExpression",
            }
        )
        return None
    text = _text_from_cell(input_expression)
    if not text:
        issues.append(
            {
                "level": "ERROR",
                "path": f"dmn.decision.{decision_id}.input.{input_id}",
                "message": "inputExpression is empty",
            }
        )
        return None
    if _contains_boolean_composition(text):
        issues.append(
            {
                "level": "ERROR",
                "path": f"dmn.decision.{decision_id}.input.{input_id}",
                "message": f"compound DMN input expression '{text}' is not allowed in DMN v1; move AND/OR/NOT logic into predicates",
            }
        )
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text):
        issues.append(
            {
                "level": "ERROR",
                "path": f"dmn.decision.{decision_id}.input.{input_id}",
                "message": f"unsupported DMN input expression '{text}'",
            }
        )
        return None
    if not text.startswith(("v_", "st_", "p_", "o_")):
        issues.append(
            {
                "level": "ERROR",
                "path": f"dmn.decision.{decision_id}.input.{input_id}",
                "message": f"DMN input expression '{text}' must use an explicit v_/st_/p_/o_ prefix",
            }
        )
    return text


def _lint_output_ref(decision_id: str, output_elem: ET.Element, issues: list[dict[str, str]]) -> str | None:
    output_id = output_elem.attrib.get("id") or "output"
    for key in ("name", "label", "id"):
        text = output_elem.attrib.get(key)
        if not text:
            continue
        if not text.startswith("o_"):
            issues.append(
                {
                    "level": "ERROR",
                    "path": f"dmn.decision.{decision_id}.output.{output_id}",
                    "message": f"DMN output identifier '{text}' must use an explicit o_ prefix",
                }
            )
        return text
    issues.append(
        {
            "level": "ERROR",
            "path": f"dmn.decision.{decision_id}.output.{output_id}",
            "message": "output is missing a usable identifier",
        }
    )
    return None


def _lint_input_cell(
    decision_id: str,
    rule_id: str,
    input_ref: str,
    cell_text: str,
    issues: list[dict[str, str]],
) -> None:
    if cell_text in {"", "-", "true", "false"}:
        return
    if _contains_boolean_composition(cell_text):
        issues.append(
            {
                "level": "ERROR",
                "path": f"dmn.decision.{decision_id}.rule.{rule_id}.input.{input_ref}",
                "message": f"input cell '{cell_text}' uses AND/OR/NOT or parentheses; DMN v1 requires compound logic to live in predicates",
            }
        )
        return
    issues.append(
        {
            "level": "ERROR",
            "path": f"dmn.decision.{decision_id}.rule.{rule_id}.input.{input_ref}",
            "message": f"unsupported DMN input cell '{cell_text}'; supported values are true, false, and -",
        }
    )


def _lint_output_cell(
    decision_id: str,
    rule_id: str,
    output_ref: str,
    cell_text: str,
    issues: list[dict[str, str]],
) -> None:
    if cell_text in {"", "-", "\"\""}:
        return
    if _contains_boolean_composition(cell_text):
        issues.append(
            {
                "level": "ERROR",
                "path": f"dmn.decision.{decision_id}.rule.{rule_id}.output.{output_ref}",
                "message": f"output cell '{cell_text}' uses AND/OR/NOT or parentheses; DMN v1 supports only scalar assignments",
            }
        )
        return
    try:
        _parse_scalar_text(cell_text)
    except DMNImportError as exc:
        issues.append(
            {
                "level": "ERROR",
                "path": f"dmn.decision.{decision_id}.rule.{rule_id}.output.{output_ref}",
                "message": str(exc),
            }
        )


def _parse_input_ref(input_elem: ET.Element) -> str:
    input_expression = _first_child_by_name(input_elem, "inputExpression")
    if input_expression is None:
        raise DMNImportError("DMN input is missing inputExpression")
    text = _text_from_cell(input_expression)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text):
        raise DMNImportError(f"unsupported DMN input expression '{text}'")
    if not text.startswith(("v_", "st_", "p_", "o_")):
        raise DMNImportError(
            f"DMN input expression '{text}' must use an explicit v_/st_/p_/o_ prefix"
        )
    return text


def _parse_output_ref(output_elem: ET.Element) -> str:
    for key in ("name", "label", "id"):
        text = output_elem.attrib.get(key)
        if text:
            if not text.startswith("o_"):
                raise DMNImportError(f"DMN output identifier '{text}' must use an explicit o_ prefix")
            return text
    raise DMNImportError("DMN output is missing a usable identifier")


def _parse_input_entry(input_ref: str, cell_text: str) -> dict[str, Any] | None:
    if cell_text in {"", "-"}:
        return None
    if cell_text == "true":
        return _symbol_ref(input_ref)
    if cell_text == "false":
        return {"kind": "not", "arg": _symbol_ref(input_ref)}
    raise DMNImportError(
        f"unsupported DMN input cell '{cell_text}' for input '{input_ref}'; supported values are true, false, and -"
    )


def _symbol_ref(identifier: str) -> dict[str, Any]:
    if identifier.startswith("p_"):
        return {"kind": "pred", "id": identifier}
    if identifier.startswith(("v_", "st_")):
        return {"kind": "var", "id": identifier}
    if identifier.startswith("o_"):
        return {"kind": "output", "id": identifier}
    raise DMNImportError(
        f"DMN identifier '{identifier}' must use an explicit v_/st_/p_/o_ prefix"
    )


def _conjoin(expressions: list[dict[str, Any]]) -> dict[str, Any]:
    if len(expressions) == 1:
        return expressions[0]
    return {"kind": "and", "args": expressions}


def _parse_scalar_text(text: str) -> Any:
    if text == "true":
        return True
    if text == "false":
        return False
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    if len(text) >= 2 and text[0] == "\"" and text[-1] == "\"":
        return text[1:-1]
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text):
        return text
    raise DMNImportError(
        f"unsupported DMN output cell '{text}'; supported values are booleans, numbers, quoted strings, identifiers, and -"
    )


def _contains_boolean_composition(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return bool(re.search(r"\b(and|or|not)\b|[()]", stripped, flags=re.IGNORECASE))


def _infer_output_def(
    decision_id: str,
    output_id: str,
    rules: list[RuleDef],
    source_id: str,
) -> OutputDef:
    seen_types: set[ScalarType] = set()
    for rule in rules:
        if output_id not in rule.then:
            continue
        seen_type = _infer_python_type(rule.then[output_id])
        if seen_type is None:
            raise DMNImportError(
                f"decision '{decision_id}' output '{output_id}' uses an unsupported assignment shape for type inference"
            )
        seen_types.add(seen_type)
    if not seen_types:
        inferred_type = ScalarType.BOOL
    elif seen_types <= {ScalarType.INT, ScalarType.DECIMAL}:
        inferred_type = ScalarType.DECIMAL if ScalarType.DECIMAL in seen_types else ScalarType.INT
    elif len(seen_types) == 1:
        inferred_type = next(iter(seen_types))
    else:
        raise DMNImportError(
            f"decision '{decision_id}' output '{output_id}' mixes incompatible assignment types: "
            + ", ".join(sorted(item.value for item in seen_types))
        )
    return OutputDef(
        id=output_id,
        type=inferred_type,
        provenance=[
            ProvenanceRecord(
                source_id=source_id,
                kind="dmn_output",
                location=f"decision:{decision_id}/output:{output_id}",
            )
        ],
    )


def _infer_python_type(value: Any) -> ScalarType | None:
    if isinstance(value, bool):
        return ScalarType.BOOL
    if isinstance(value, int) and not isinstance(value, bool):
        return ScalarType.INT
    if isinstance(value, float):
        return ScalarType.DECIMAL
    if isinstance(value, str):
        return ScalarType.STRING
    return None


def _children_by_name(parent: ET.Element, local_name: str) -> list[ET.Element]:
    return [child for child in list(parent) if _local_name(child.tag) == local_name]


def _first_child_by_name(parent: ET.Element, local_name: str) -> ET.Element | None:
    for child in parent:
        if _local_name(child.tag) == local_name:
            return child
    return None


def _text_from_cell(elem: ET.Element) -> str:
    direct_text = (elem.text or "").strip()
    if direct_text:
        return direct_text
    text_elem = _first_child_by_name(elem, "text")
    return (text_elem.text or "").strip() if text_elem is not None else ""


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _slug_to_identifier(text: str, prefix: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower() or prefix
    return slug if slug.startswith(f"{prefix}_") else f"{prefix}_{slug}"
