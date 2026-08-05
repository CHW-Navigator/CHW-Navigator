from __future__ import annotations

import copy
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Literal

from .clinical_ir import ClinicalIRDocument, ScalarType
from .diagnostics import Diagnostic, DiagnosticCode
from .form_ir import SurveyRow
from .xlsform_backend import BuiltXLSForm


CHT_LOCAL_DATA_SCHEMA_VERSION = "cht-local-data-bindings@1.0.0"
CHTFormContext = Literal["contact", "task", "reports"]

_BINDING_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,159}@[0-9]+\.[0-9]+\.[0-9]+$")
_PATH_SEGMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,127}$")
_VALUE_TYPES = {"int", "decimal", "string", "string_key"}
_ADAPTER_CONTEXTS: dict[str, frozenset[str]] = {
    "cht_contact_field": frozenset({"contact", "task"}),
    "cht_contact_summary": frozenset({"contact"}),
    "cht_task_input": frozenset({"task"}),
}


@dataclass(frozen=True, slots=True)
class CHTLocalDataBinding:
    binding_id: str
    semantic_name: str
    description: str
    value_type: str
    unit: str | None
    subject: str
    adapter_kind: str
    path: tuple[str, ...]
    available_contexts: tuple[str, ...]
    freshness_policy: str
    recorded_at_path: tuple[str, ...] | None = None
    max_age_days: int | None = None


@dataclass(frozen=True, slots=True)
class CHTLocalDataRegistry:
    schema_version: str
    target_cht_version: str
    bindings: dict[str, CHTLocalDataBinding]


@dataclass(frozen=True, slots=True)
class CHTLocalDataReadPlan:
    action_id: str
    binding_id: str
    target_var: str
    source_xpath: str
    recorded_at_xpath: str | None
    status_row: str
    fallback_row: str | None
    fail_mode: str
    freshness_policy: str


class CHTLocalDataLoweringError(ValueError):
    def __init__(self, diagnostics: list[Diagnostic] | tuple[Diagnostic, ...]):
        self.diagnostics = tuple(diagnostics)
        super().__init__(
            "CHT local-data lowering failed closed:\n"
            + "\n".join(f"{item.code}: {item.message}" for item in self.diagnostics)
        )


def _diagnostic(code: DiagnosticCode, message: str, path: str | None = None) -> Diagnostic:
    return Diagnostic(code=code, severity="error", message=message, path=path)


def load_cht_local_data_registry(path: str | Path) -> CHTLocalDataRegistry:
    registry_path = Path(path)
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CHTLocalDataLoweringError(
            [
                _diagnostic(
                    DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                    f"Could not load local-data bindings: {exc}",
                    str(registry_path),
                )
            ]
        ) from exc
    return parse_cht_local_data_registry(payload)


def parse_cht_local_data_registry(payload: Any) -> CHTLocalDataRegistry:
    diagnostics: list[Diagnostic] = []
    root = _object(payload, "$", diagnostics)
    _reject_unknown(root, {"schema_version", "target_cht_version", "bindings"}, "$", diagnostics)
    schema_version = _string(root.get("schema_version"), "$.schema_version", diagnostics)
    if schema_version and schema_version != CHT_LOCAL_DATA_SCHEMA_VERSION:
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                f"Unsupported local-data binding schema '{schema_version}'.",
                "$.schema_version",
            )
        )
    target_cht_version = _string(root.get("target_cht_version"), "$.target_cht_version", diagnostics)
    raw_bindings = _object(root.get("bindings"), "$.bindings", diagnostics)
    if not raw_bindings:
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                "At least one local-data binding is required.",
                "$.bindings",
            )
        )

    bindings: dict[str, CHTLocalDataBinding] = {}
    for binding_id, raw in sorted(raw_bindings.items()):
        path = f"$.bindings.{binding_id}"
        if not isinstance(binding_id, str) or _BINDING_ID.fullmatch(binding_id) is None:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                    "Binding IDs must be stable names ending in @major.minor.patch.",
                    path,
                )
            )
        item = _object(raw, path, diagnostics)
        _reject_unknown(
            item,
            {
                "semantic_name",
                "description",
                "value_type",
                "unit",
                "subject",
                "adapter",
                "available_contexts",
                "freshness",
            },
            path,
            diagnostics,
        )
        semantic_name = _string(item.get("semantic_name"), f"{path}.semantic_name", diagnostics)
        description = _string(item.get("description"), f"{path}.description", diagnostics)
        value_type = _string(item.get("value_type"), f"{path}.value_type", diagnostics)
        if value_type and value_type not in _VALUE_TYPES:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                    f"Unsupported value_type '{value_type}'.",
                    f"{path}.value_type",
                )
            )
        unit = item.get("unit")
        if unit is not None and (not isinstance(unit, str) or not unit):
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                    "unit must be a non-empty string when supplied.",
                    f"{path}.unit",
                )
            )
            unit = None
        if value_type in {"int", "decimal"} and not unit:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                    "Numeric local-data bindings must declare a unit.",
                    f"{path}.unit",
                )
            )
        subject = _string(item.get("subject"), f"{path}.subject", diagnostics)
        if subject and subject != "current_person":
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                    "The first registry version only supports subject='current_person'.",
                    f"{path}.subject",
                )
            )

        adapter = _object(item.get("adapter"), f"{path}.adapter", diagnostics)
        _reject_unknown(adapter, {"kind", "path"}, f"{path}.adapter", diagnostics)
        adapter_kind = _string(adapter.get("kind"), f"{path}.adapter.kind", diagnostics)
        if adapter_kind and adapter_kind not in _ADAPTER_CONTEXTS:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                    f"Unsupported adapter kind '{adapter_kind}'.",
                    f"{path}.adapter.kind",
                )
            )
        value_path = _data_path(adapter.get("path"), f"{path}.adapter.path", diagnostics)

        raw_contexts = item.get("available_contexts")
        contexts: tuple[str, ...] = ()
        if not isinstance(raw_contexts, list) or not raw_contexts:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                    "available_contexts must be a non-empty array.",
                    f"{path}.available_contexts",
                )
            )
        else:
            contexts = tuple(str(value) for value in raw_contexts)
            invalid_contexts = sorted(set(contexts) - {"contact", "task", "reports"})
            if invalid_contexts:
                diagnostics.append(
                    _diagnostic(
                        DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                        f"Unknown form contexts: {', '.join(invalid_contexts)}.",
                        f"{path}.available_contexts",
                    )
                )
            unsupported = sorted(set(contexts) - _ADAPTER_CONTEXTS.get(adapter_kind, frozenset()))
            if unsupported:
                diagnostics.append(
                    _diagnostic(
                        DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                        f"Adapter '{adapter_kind}' cannot provide contexts: {', '.join(unsupported)}.",
                        f"{path}.available_contexts",
                    )
                )

        freshness = _object(item.get("freshness"), f"{path}.freshness", diagnostics)
        _reject_unknown(
            freshness,
            {"policy", "recorded_at_path", "max_age_days"},
            f"{path}.freshness",
            diagnostics,
        )
        freshness_policy = _string(freshness.get("policy"), f"{path}.freshness.policy", diagnostics)
        recorded_at_path: tuple[str, ...] | None = None
        max_age_days: int | None = None
        if freshness_policy == "immutable":
            if "recorded_at_path" in freshness or "max_age_days" in freshness:
                diagnostics.append(
                    _diagnostic(
                        DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                        "Immutable bindings must not define recorded_at_path or max_age_days.",
                        f"{path}.freshness",
                    )
                )
        elif freshness_policy == "max_age_days":
            recorded_at_path = _data_path(
                freshness.get("recorded_at_path"),
                f"{path}.freshness.recorded_at_path",
                diagnostics,
            )
            raw_max_age = freshness.get("max_age_days")
            if isinstance(raw_max_age, bool) or not isinstance(raw_max_age, int) or raw_max_age < 0:
                diagnostics.append(
                    _diagnostic(
                        DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                        "max_age_days must be a non-negative integer.",
                        f"{path}.freshness.max_age_days",
                    )
                )
            else:
                max_age_days = raw_max_age
        elif freshness_policy:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                    f"Unsupported freshness policy '{freshness_policy}'.",
                    f"{path}.freshness.policy",
                )
            )

        bindings[str(binding_id)] = CHTLocalDataBinding(
            binding_id=str(binding_id),
            semantic_name=semantic_name,
            description=description,
            value_type=value_type,
            unit=unit if isinstance(unit, str) else None,
            subject=subject,
            adapter_kind=adapter_kind,
            path=value_path,
            available_contexts=contexts,
            freshness_policy=freshness_policy,
            recorded_at_path=recorded_at_path,
            max_age_days=max_age_days,
        )

    _validate_path_collisions(bindings, diagnostics)

    if diagnostics:
        raise CHTLocalDataLoweringError(diagnostics)
    return CHTLocalDataRegistry(
        schema_version=schema_version,
        target_cht_version=target_cht_version,
        bindings=bindings,
    )


def lower_cht_local_data_reads(
    document: ClinicalIRDocument,
    built: BuiltXLSForm,
    registry: CHTLocalDataRegistry,
    *,
    form_context: CHTFormContext,
) -> tuple[CHTLocalDataReadPlan, ...]:
    diagnostics: list[Diagnostic] = []
    pending: list[tuple[Any, Any, CHTLocalDataBinding]] = []
    claimed_targets: set[str] = set()
    for action in document.actions.values():
        if action.kind not in {"read_history", "read_local_data"}:
            continue
        binding = registry.bindings.get(action.source or "")
        if binding is None:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CHT_LOCAL_DATA_BINDING_UNBOUND,
                    f"Action '{action.id}' references unknown binding '{action.source}'.",
                    f"actions.{action.id}.source",
                )
            )
            continue
        if len(action.mappings) != 1:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                    "Version 1 local-data actions must contain exactly one value mapping.",
                    f"actions.{action.id}.mappings",
                )
            )
        if form_context not in binding.available_contexts:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CHT_LOCAL_DATA_CONTEXT_UNAVAILABLE,
                    f"Binding '{binding.binding_id}' is unavailable when the form is launched from '{form_context}'.",
                    f"actions.{action.id}.source",
                )
            )
        for mapping in action.mappings:
            if mapping.record_key != "value":
                diagnostics.append(
                    _diagnostic(
                        DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                        "Version 1 local-data mappings must use record_key='value'.",
                        f"actions.{action.id}.mappings",
                    )
                )
                continue
            variable = document.variables.get(mapping.target_var)
            if variable is None:
                continue
            expected_outputs = {mapping.target_var}
            if mapping.recorded_at_target_var is not None:
                expected_outputs.add(mapping.recorded_at_target_var)
            if set(action.outputs) != expected_outputs:
                diagnostics.append(
                    _diagnostic(
                        DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                        "Action outputs must exactly match its value and recorded-at mapping targets.",
                        f"actions.{action.id}.outputs",
                    )
                )
            if mapping.target_var in claimed_targets:
                diagnostics.append(
                    _diagnostic(
                        DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                        f"Multiple local-data actions target '{mapping.target_var}'.",
                        f"actions.{action.id}.mappings",
                    )
                )
            claimed_targets.add(mapping.target_var)
            if variable.type.value != binding.value_type or (
                binding.unit is not None and variable.unit != binding.unit
            ):
                expected = binding.value_type + (f" [{binding.unit}]" if binding.unit else "")
                actual = variable.type.value + (f" [{variable.unit}]" if variable.unit else "")
                diagnostics.append(
                    _diagnostic(
                        DiagnosticCode.CHT_LOCAL_DATA_TYPE_MISMATCH,
                        f"Binding '{binding.binding_id}' provides {expected}, but '{variable.id}' is {actual}.",
                        f"actions.{action.id}.mappings",
                    )
                )
            if variable.history_binding is None or variable.history_binding.record_key != binding.binding_id:
                diagnostics.append(
                    _diagnostic(
                        DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                        f"Variable '{variable.id}' must repeat the exact binding ID in history_binding.record_key.",
                        f"variables.{variable.id}.history_binding.record_key",
                    )
                )
            if binding.freshness_policy == "max_age_days":
                if mapping.recorded_at_target_var is None:
                    diagnostics.append(
                        _diagnostic(
                            DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                            f"Freshness-limited binding '{binding.binding_id}' requires recorded_at_target_var.",
                            f"actions.{action.id}.mappings",
                        )
                    )
                else:
                    recorded_variable = document.variables.get(mapping.recorded_at_target_var)
                    if recorded_variable is not None and recorded_variable.type is not ScalarType.STRING:
                        diagnostics.append(
                            _diagnostic(
                                DiagnosticCode.CHT_LOCAL_DATA_TYPE_MISMATCH,
                                "recorded_at_target_var must be a string variable containing an ISO date.",
                                f"actions.{action.id}.mappings",
                            )
                        )
                if (
                    variable.history_binding is not None
                    and variable.history_binding.freshness_max_age_days != binding.max_age_days
                ):
                    diagnostics.append(
                        _diagnostic(
                            DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                            f"Variable '{variable.id}' must use registry freshness_max_age_days={binding.max_age_days}.",
                            f"variables.{variable.id}.history_binding.freshness_max_age_days",
                        )
                    )
            if action.fail_mode == "soft_missing" and not variable.allowed_missingness:
                diagnostics.append(
                    _diagnostic(
                        DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                        f"soft_missing requires '{variable.id}' to allow missing values.",
                        f"actions.{action.id}.fail_mode",
                    )
                )
            pending.append((action, mapping, binding))

    if diagnostics:
        raise CHTLocalDataLoweringError(diagnostics)

    input_paths: dict[str, set[tuple[str, ...]]] = {"cht_contact_field": set(), "cht_task_input": set()}
    for _, _, binding in pending:
        if binding.adapter_kind in input_paths:
            input_paths[binding.adapter_kind].add(binding.path)
            if binding.recorded_at_path is not None:
                input_paths[binding.adapter_kind].add(binding.recorded_at_path)
    input_rows = _input_rows(input_paths)
    if input_rows:
        built.workbook.survey[0:0] = input_rows
        for row in input_rows:
            built.row_sources.setdefault(row.name, [])

    plans: list[CHTLocalDataReadPlan] = []
    for action, mapping, binding in pending:
        source_xpath = _binding_xpath(binding, binding.path)
        recorded_at_xpath = (
            _binding_xpath(binding, binding.recorded_at_path)
            if binding.recorded_at_path is not None
            else None
        )
        target_index = next(
            (index for index, row in enumerate(built.workbook.survey) if row.name == mapping.target_var),
            None,
        )
        if target_index is None:
            raise AssertionError(f"XLSForm target row '{mapping.target_var}' was not generated")
        original = built.workbook.survey[target_index]
        status_row = f"local_status__{mapping.target_var}"
        invalid = _invalid_expression(source_xpath, recorded_at_xpath, binding.max_age_days)
        status = SurveyRow(
            type="calculate",
            name=status_row,
            calculation=_status_expression(source_xpath, recorded_at_xpath, binding.max_age_days),
            role="local_data_status",
        )
        fallback_row: str | None = None
        fail_mode = action.fail_mode or "soft_missing"
        replacement = SurveyRow(
            type="calculate",
            name=mapping.target_var,
            calculation=f"if({invalid}, '', {source_xpath})",
            required="yes" if fail_mode == "hard_error" else "",
            role="local_data_value",
        )
        inserted: list[SurveyRow] = [status]
        if fail_mode == "ask_if_missing":
            fallback_row = f"local_fallback__{mapping.target_var}"
            fallback = copy.deepcopy(original)
            fallback.name = fallback_row
            fallback.relevant = f"${{{status_row}}} != 'available'"
            fallback.calculation = ""
            fallback.required = "yes"
            fallback.role = "local_data_fallback"
            replacement.calculation = f"if({invalid}, ${{{fallback_row}}}, {source_xpath})"
            inserted.append(fallback)
        elif fail_mode == "hard_error":
            inserted.append(
                SurveyRow(
                    type="note",
                    name=f"local_error__{mapping.target_var}",
                    label=f"Required local data for {binding.semantic_name} is unavailable or stale.",
                    relevant=f"${{{status_row}}} != 'available'",
                    role="local_data_error",
                )
            )
        inserted.append(replacement)
        built.workbook.survey[target_index : target_index + 1] = inserted
        sources = built.row_sources.pop(mapping.target_var, [])
        for row in inserted:
            built.row_sources[row.name] = list(sources)

        if mapping.recorded_at_target_var is not None and recorded_at_xpath is not None:
            recorded_index = next(
                (
                    index
                    for index, row in enumerate(built.workbook.survey)
                    if row.name == mapping.recorded_at_target_var
                ),
                None,
            )
            if recorded_index is not None:
                recorded_original = built.workbook.survey[recorded_index]
                recorded_original.type = "calculate"
                recorded_original.label = ""
                recorded_original.calculation = recorded_at_xpath
                recorded_original.required = ""
                recorded_original.role = "local_data_recorded_at"

        plans.append(
            CHTLocalDataReadPlan(
                action_id=action.id,
                binding_id=binding.binding_id,
                target_var=mapping.target_var,
                source_xpath=source_xpath,
                recorded_at_xpath=recorded_at_xpath,
                status_row=status_row,
                fallback_row=fallback_row,
                fail_mode=fail_mode,
                freshness_policy=binding.freshness_policy,
            )
        )
    return tuple(plans)


def _object(value: Any, path: str, diagnostics: list[Diagnostic]) -> dict[str, Any]:
    if not isinstance(value, dict):
        diagnostics.append(
            _diagnostic(DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID, f"{path} must be an object.", path)
        )
        return {}
    return value


def _string(value: Any, path: str, diagnostics: list[Diagnostic]) -> str:
    if not isinstance(value, str) or not value:
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                f"{path} must be a non-empty string.",
                path,
            )
        )
        return ""
    return value


def _reject_unknown(
    value: dict[str, Any],
    allowed: set[str],
    path: str,
    diagnostics: list[Diagnostic],
) -> None:
    for key in sorted(set(value) - allowed):
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                f"Unknown field '{key}'.",
                f"{path}.{key}",
            )
        )


def _data_path(value: Any, path: str, diagnostics: list[Diagnostic]) -> tuple[str, ...]:
    if not isinstance(value, str) or not value:
        diagnostics.append(
            _diagnostic(DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID, f"{path} is invalid.", path)
        )
        return ()
    segments = tuple(value.split("."))
    if any(_PATH_SEGMENT.fullmatch(segment) is None for segment in segments):
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                f"{path} must contain only dot-separated data field names.",
                path,
            )
        )
        return ()
    return segments


def _validate_path_collisions(
    bindings: dict[str, CHTLocalDataBinding], diagnostics: list[Diagnostic]
) -> None:
    by_adapter: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
    for binding in bindings.values():
        paths = [binding.path]
        if binding.recorded_at_path is not None:
            paths.append(binding.recorded_at_path)
        for path in paths:
            by_adapter.setdefault(binding.adapter_kind, []).append((binding.binding_id, path))
        if binding.adapter_kind == "cht_task_input" and binding.path and binding.path[0] in {
            "source",
            "source_id",
            "task_id",
            "contact",
        }:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                    f"Task-input binding '{binding.binding_id}' collides with a reserved CHT input field.",
                    f"$.bindings.{binding.binding_id}.adapter.path",
                )
            )
    for adapter_kind, entries in by_adapter.items():
        for index, (left_id, left) in enumerate(entries):
            for right_id, right in entries[index + 1 :]:
                if left == right:
                    continue
                shorter, longer = (left, right) if len(left) < len(right) else (right, left)
                if longer[: len(shorter)] == shorter:
                    diagnostics.append(
                        _diagnostic(
                            DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                            f"Bindings '{left_id}' and '{right_id}' use colliding {adapter_kind} paths.",
                            "$.bindings",
                        )
                    )


def _binding_xpath(binding: CHTLocalDataBinding, path: tuple[str, ...] | None) -> str:
    if path is None:
        raise AssertionError("binding XPath requested without a path")
    suffix = "/".join(path)
    if binding.adapter_kind == "cht_contact_field":
        return f"../inputs/contact/{suffix}"
    if binding.adapter_kind == "cht_task_input":
        return f"../inputs/{suffix}"
    if binding.adapter_kind == "cht_contact_summary":
        return f"instance('contact-summary')/context/{suffix}"
    raise AssertionError(f"unsupported adapter '{binding.adapter_kind}'")


def _missing(xpath: str) -> str:
    return f"string-length(normalize-space(string({xpath}))) = 0"


def _invalid_expression(value_xpath: str, recorded_at_xpath: str | None, max_age_days: int | None) -> str:
    if recorded_at_xpath is None or max_age_days is None:
        return _missing(value_xpath)
    return (
        f"({_missing(value_xpath)}) or ({_missing(recorded_at_xpath)}) or "
        f"(cht:difference-in-days(date({recorded_at_xpath}), today()) > {max_age_days})"
    )


def _status_expression(value_xpath: str, recorded_at_xpath: str | None, max_age_days: int | None) -> str:
    if recorded_at_xpath is None or max_age_days is None:
        return f"if({_missing(value_xpath)}, 'missing', 'available')"
    return (
        f"if({_missing(value_xpath)}, 'missing', "
        f"if(({_missing(recorded_at_xpath)}) or "
        f"(cht:difference-in-days(date({recorded_at_xpath}), today()) > {max_age_days}), "
        "'stale', 'available'))"
    )


def _input_rows(paths: dict[str, set[tuple[str, ...]]]) -> list[SurveyRow]:
    contact_paths = paths["cht_contact_field"]
    task_paths = paths["cht_task_input"]
    if not contact_paths and not task_paths:
        return []
    rows = [
        SurveyRow(type="begin group", name="inputs", label="NO_LABEL", relevant="./source = 'user'", appearance="field-list", role="cht_inputs"),
        SurveyRow(type="hidden", name="source", label="Source", role="cht_input"),
        SurveyRow(type="hidden", name="source_id", label="Source ID", role="cht_input"),
        SurveyRow(type="hidden", name="task_id", label="Task ID", role="cht_input"),
    ]
    rows.extend(_path_tree_rows(task_paths, role="cht_task_input"))
    if contact_paths:
        rows.append(SurveyRow(type="begin group", name="contact", label="NO_LABEL", role="cht_contact"))
        rows.append(
            SurveyRow(
                type="string",
                name="_id",
                label="Contact ID",
                appearance="select-contact type-person",
                role="cht_contact_selector",
            )
        )
        rows.extend(_path_tree_rows(contact_paths, role="cht_contact_field"))
        rows.append(SurveyRow(type="end group", name="contact", role="cht_contact"))
    rows.append(SurveyRow(type="end group", name="inputs", role="cht_inputs"))
    return rows


def _path_tree_rows(paths: set[tuple[str, ...]], *, role: str) -> list[SurveyRow]:
    tree: dict[str, Any] = {}
    for path in sorted(paths):
        node = tree
        for segment in path[:-1]:
            node = node.setdefault(segment, {})
        node[path[-1]] = None

    def emit(node: dict[str, Any]) -> list[SurveyRow]:
        result: list[SurveyRow] = []
        for name, child in sorted(node.items()):
            if child is None:
                if name == "_id":
                    continue
                result.append(SurveyRow(type="hidden", name=name, label=name, role=role))
            else:
                result.append(SurveyRow(type="begin group", name=name, label="NO_LABEL", role=role))
                result.extend(emit(child))
                result.append(SurveyRow(type="end group", name=name, role=role))
        return result

    return emit(tree)
