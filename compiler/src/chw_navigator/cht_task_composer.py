from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from .diagnostics import Diagnostic, DiagnosticCode


BEGIN_MARKER = "/* CHW-NAVIGATOR-GENERATED-RULES-BEGIN"
END_MARKER = "/* CHW-NAVIGATOR-GENERATED-RULES-END */"
VARIABLE_NAME = "__CHW_NAVIGATOR_GENERATED_RULES__"
_EXPORT = re.compile(r"\bmodule\s*\.\s*exports\s*=\s*\[")
_CONST_OBJECT = re.compile(r"\bconst\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*\{")
_NAME = re.compile(r"\bname\s*:\s*(['\"])([^'\"]+)\1")
_EVENTS = re.compile(r"\bevents\s*:\s*\[")
_EVENT_ID = re.compile(r"\bid\s*:\s*(['\"])([^'\"]+)\1")


@dataclass(frozen=True, slots=True)
class TaskRuleIdentity:
    name: str
    event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PythonTaskComposition:
    content: str
    evidence: dict[str, Any]
    state: dict[str, Any]


class CHTTaskCompositionError(ValueError):
    def __init__(self, diagnostics: list[Diagnostic] | tuple[Diagnostic, ...]):
        self.diagnostics = tuple(diagnostics)
        super().__init__(
            "CHT task composition failed closed:\n"
            + "\n".join(f"{item.code}: {item.message}" for item in self.diagnostics)
        )


def _diagnostic(message: str, path: str = "tasks.js") -> Diagnostic:
    return Diagnostic(
        code=DiagnosticCode.CHT_COMPOSITION_INVALID,
        severity="error",
        message=message,
        path=path,
    )


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _scan_balanced(source: str, opening: int, open_char: str, close_char: str) -> int:
    depth = 0
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = opening
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if line_comment:
            if char in "\r\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if char == "*" and following == "/":
                block_comment = False
                index += 2
                continue
            index += 1
            continue
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in "'\"`":
            quote = char
        elif char == "/" and following == "/":
            line_comment = True
            index += 2
            continue
        elif char == "/" and following == "*":
            block_comment = True
            index += 2
            continue
        elif char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise CHTTaskCompositionError([_diagnostic(f"Unclosed {open_char}{close_char} block.")])


def _export_range(source: str) -> tuple[int, int, int]:
    matches = list(_EXPORT.finditer(source))
    if len(matches) != 1:
        raise CHTTaskCompositionError(
            [_diagnostic("Exactly one literal module.exports task array is required.")]
        )
    match = matches[0]
    opening = source.find("[", match.start())
    closing = _scan_balanced(source, opening, "[", "]")
    return match.start(), opening, closing


def _top_level_elements(array_text: str) -> list[str]:
    elements: list[str] = []
    start = 0
    depths = {"(": 0, "[": 0, "{": 0}
    pairs = {")": "(", "]": "[", "}": "{"}
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = 0
    while index < len(array_text):
        char = array_text[index]
        following = array_text[index + 1] if index + 1 < len(array_text) else ""
        if line_comment:
            if char in "\r\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if char == "*" and following == "/":
                block_comment = False
                index += 2
                continue
            index += 1
            continue
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in "'\"`":
            quote = char
        elif char == "/" and following == "/":
            line_comment = True
            index += 2
            continue
        elif char == "/" and following == "*":
            block_comment = True
            index += 2
            continue
        elif char in depths:
            depths[char] += 1
        elif char in pairs:
            depths[pairs[char]] -= 1
        elif char == "," and all(value == 0 for value in depths.values()):
            item = array_text[start:index].strip()
            if item:
                elements.append(item)
            start = index + 1
        index += 1
    tail = array_text[start:].strip()
    if tail:
        elements.append(tail)
    return elements


def _object_declarations(source: str) -> dict[str, str]:
    declarations: dict[str, str] = {}
    for match in _CONST_OBJECT.finditer(source):
        opening = source.find("{", match.start())
        closing = _scan_balanced(source, opening, "{", "}")
        declarations[match.group(1)] = source[opening : closing + 1]
    return declarations


def _identity(object_text: str) -> TaskRuleIdentity:
    name_match = _NAME.search(object_text)
    if name_match is None:
        raise CHTTaskCompositionError([_diagnostic("Every task rule needs a literal name.")])
    event_ids: list[str] = []
    events_match = _EVENTS.search(object_text)
    if events_match is not None:
        opening = object_text.find("[", events_match.start())
        closing = _scan_balanced(object_text, opening, "[", "]")
        event_ids = [match.group(2) for match in _EVENT_ID.finditer(object_text[opening : closing + 1])]
    if len(event_ids) != len(set(event_ids)):
        raise CHTTaskCompositionError([_diagnostic(f"Task rule '{name_match.group(2)}' repeats an event id.")])
    return TaskRuleIdentity(name=name_match.group(2), event_ids=tuple(sorted(event_ids)))


def extract_task_identities(source: str, *, allow_managed_spread: bool = False) -> tuple[TaskRuleIdentity, ...]:
    export_start, opening, closing = _export_range(source)
    declarations = _object_declarations(source[:export_start])
    identities: list[TaskRuleIdentity] = []
    for element in _top_level_elements(source[opening + 1 : closing]):
        if element == f"...{VARIABLE_NAME}" and allow_managed_spread:
            continue
        if element.startswith("..."):
            raise CHTTaskCompositionError([_diagnostic("Unmanaged task-array spreads are not supported.")])
        object_text = element if element.startswith("{") else declarations.get(element)
        if object_text is None:
            raise CHTTaskCompositionError(
                [_diagnostic("Task-array entries must be object literals or top-level const objects.")]
            )
        identities.append(_identity(object_text))
    names = [item.name for item in identities]
    events = [event for item in identities for event in item.event_ids]
    if len(names) != len(set(names)) or len(events) != len(set(events)):
        raise CHTTaskCompositionError([_diagnostic("Task rule names and event ids must be unique.")])
    return tuple(sorted(identities, key=lambda item: item.name))


def _managed_range(source: str) -> tuple[int, int] | None:
    start = source.find(BEGIN_MARKER)
    end_start = source.find(END_MARKER)
    if start < 0 and end_start < 0:
        return None
    if start < 0 or end_start < start:
        raise CHTTaskCompositionError([_diagnostic("Managed task markers are incomplete or out of order.")])
    if source.find(BEGIN_MARKER, start + len(BEGIN_MARKER)) >= 0 or source.find(
        END_MARKER, end_start + len(END_MARKER)
    ) >= 0:
        raise CHTTaskCompositionError([_diagnostic("Multiple managed task blocks are forbidden.")])
    return start, end_start + len(END_MARKER)


def _generated_parts(source: str) -> tuple[str, str, tuple[TaskRuleIdentity, ...]]:
    export_start, opening, closing = _export_range(source)
    prelude = source[:export_start].strip()
    exported = source[opening : closing + 1]
    return prelude, exported, extract_task_identities(source)


def _block(generated_source: str) -> tuple[str, tuple[TaskRuleIdentity, ...]]:
    prelude, exported, identities = _generated_parts(generated_source)
    metadata = json.dumps(
        {
            "eventIds": sorted(event for item in identities for event in item.event_ids),
            "generatedTasksSha256": _sha256_text(generated_source),
            "ruleNames": [item.name for item in identities],
            "schemaVersion": "1.0.0",
            "variableName": VARIABLE_NAME,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    indented_prelude = "\n".join(f"  {line}" if line else "" for line in prelude.splitlines())
    indented_export = "\n".join(f"  {line}" if line else "" for line in exported.splitlines())
    block = (
        f"{BEGIN_MARKER}\n{metadata}\n*/\n"
        f"const {VARIABLE_NAME} = (() => {{\n"
        f"{indented_prelude + chr(10) if indented_prelude else ''}"
        f"  return {indented_export.lstrip()};\n"
        f"}})();\n{END_MARKER}"
    )
    return block, identities


def _insert_spread(source: str) -> str:
    _, opening, closing = _export_range(source)
    inner = source[opening + 1 : closing]
    trimmed = inner.rstrip()
    if not trimmed:
        insertion = f"\n  ...{VARIABLE_NAME}\n"
    elif trimmed.endswith(","):
        insertion = f"\n  ...{VARIABLE_NAME}"
    else:
        insertion = f",\n  ...{VARIABLE_NAME}"
    return source[:closing] + insertion + source[closing:]


def _compose_once(
    destination_source: str,
    generated_source: str,
    previous_state: dict[str, Any] | None,
) -> tuple[str, dict[str, Any], tuple[TaskRuleIdentity, ...], tuple[TaskRuleIdentity, ...]]:
    block, generated = _block(generated_source)
    managed = _managed_range(destination_source)
    existing = extract_task_identities(destination_source, allow_managed_spread=managed is not None)
    existing_names = {item.name for item in existing}
    existing_events = {event for item in existing for event in item.event_ids}
    collisions = [item.name for item in generated if item.name in existing_names]
    collisions.extend(event for item in generated for event in item.event_ids if event in existing_events)
    if collisions:
        raise CHTTaskCompositionError(
            [_diagnostic("Generated task identities collide with existing tasks: " + ", ".join(sorted(collisions)))]
        )
    if managed is None:
        if previous_state is not None:
            raise CHTTaskCompositionError([_diagnostic("Composition state exists but the managed block is absent.")])
        if re.search(rf"\b{re.escape(VARIABLE_NAME)}\b", destination_source):
            raise CHTTaskCompositionError([_diagnostic("The reserved managed-task variable already exists.")])
        export_start, _, _ = _export_range(destination_source)
        composed = destination_source[:export_start] + block + "\n\n" + destination_source[export_start:]
        composed = _insert_spread(composed)
    else:
        if previous_state is None:
            raise CHTTaskCompositionError([_diagnostic("A managed block exists without trusted composition state.")])
        start, end = managed
        current_hash = _sha256_text(destination_source[start:end])
        if current_hash != previous_state.get("block_sha256"):
            raise CHTTaskCompositionError([_diagnostic("Managed task block differs from the trusted previous hash.")])
        if destination_source.count(f"...{VARIABLE_NAME}") != 1:
            raise CHTTaskCompositionError([_diagnostic("Exactly one managed task spread is required.")])
        composed = destination_source[:start] + block + destination_source[end:]
    composed_range = _managed_range(composed)
    assert composed_range is not None
    state = {
        "schema_version": "python-task-composition@1.0.0",
        "block_sha256": _sha256_text(composed[composed_range[0] : composed_range[1]]),
        "composed_sha256": _sha256_text(composed),
        "generated_tasks_sha256": _sha256_text(generated_source),
        "variable_name": VARIABLE_NAME,
        "rule_names": [item.name for item in generated],
        "event_ids": sorted(event for item in generated for event in item.event_ids),
    }
    return composed, state, existing, generated


def compose_tasks_js(
    destination_source: str,
    generated_source: str,
    *,
    previous_state: dict[str, Any] | None = None,
) -> PythonTaskComposition:
    composed, state, existing, generated = _compose_once(
        destination_source, generated_source, previous_state
    )
    second, _, _, _ = _compose_once(composed, generated_source, state)
    if second != composed:
        raise CHTTaskCompositionError([_diagnostic("A second composition was not byte-identical.")])
    evidence = {
        "schema_version": "python-task-composition-evidence@1.0.0",
        "destination_before_sha256": _sha256_text(destination_source),
        "generated_tasks_sha256": _sha256_text(generated_source),
        "composed_sha256": _sha256_text(composed),
        "block_sha256": state["block_sha256"],
        "existing_rule_identities": [
            {"name": item.name, "event_ids": list(item.event_ids)} for item in existing
        ],
        "generated_rule_identities": [
            {"name": item.name, "event_ids": list(item.event_ids)} for item in generated
        ],
        "second_composition_byte_identical": True,
    }
    return PythonTaskComposition(content=composed, evidence=evidence, state=state)
