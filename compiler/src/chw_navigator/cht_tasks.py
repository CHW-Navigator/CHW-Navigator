from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .clinical_ir import ActionDef, ClinicalIRDocument
from .clinical_vocabulary import reject_clinical_derivation
from .diagnostics import Diagnostic, DiagnosticCode
from .form_ir import SurveyRow


CHT_TASK_BINDING_SCHEMA_VERSION = "cht-task-bindings@1.0.0"
_SAFE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_SAFE_TRANSLATION_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")
_SAFE_ROLE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SAFE_MESSAGE_KEY = re.compile(r"^m_[a-z0-9][a-z0-9_]{0,125}$")


@dataclass(frozen=True, slots=True)
class CHTTaskPriority:
    level: int
    label: str


@dataclass(frozen=True, slots=True)
class CHTTaskTypeBinding:
    logical_name: str
    source_message_key: str
    title_key: str
    followup_form: str
    permission_key: str
    icon: str
    start_days: int
    end_days: int
    source_priority: str | None = None
    assignee_role: str | None = None
    priority: CHTTaskPriority | None = None


@dataclass(frozen=True, slots=True)
class CHTTaskBindingRegistry:
    schema_version: str
    target_cht_version: str
    task_types: dict[str, CHTTaskTypeBinding]


@dataclass(frozen=True, slots=True)
class CHTTaskIntentPlan:
    action_id: str
    step: str
    group: str
    name: str
    event_id: str
    source_form_code: str
    due_days: int
    required_calculation: str
    operation_id_calculation: str
    binding: CHTTaskTypeBinding
    message_key: str | None = None


class CHTTaskLoweringError(ValueError):
    def __init__(self, diagnostics: list[Diagnostic] | tuple[Diagnostic, ...]):
        self.diagnostics = tuple(diagnostics)
        super().__init__(
            "CHT task lowering failed closed:\n"
            + "\n".join(f"{item.code}: {item.message}" for item in self.diagnostics)
        )


def _diagnostic(code: DiagnosticCode, message: str, path: str | None = None) -> Diagnostic:
    return Diagnostic(code=code, severity="error", message=message, path=path)


def _require_object(value: Any, *, path: str, diagnostics: list[Diagnostic]) -> dict[str, Any]:
    if not isinstance(value, dict):
        diagnostics.append(
            _diagnostic(DiagnosticCode.CHT_TASK_BINDING_INVALID, f"{path} must be an object.", path)
        )
        return {}
    return value


def _require_string(
    value: Any,
    *,
    path: str,
    diagnostics: list[Diagnostic],
    pattern: re.Pattern[str] | None = None,
) -> str:
    if not isinstance(value, str) or not value or (pattern is not None and pattern.fullmatch(value) is None):
        diagnostics.append(
            _diagnostic(DiagnosticCode.CHT_TASK_BINDING_INVALID, f"{path} is invalid.", path)
        )
        return ""
    return value


def _require_non_negative_integer(value: Any, *, path: str, diagnostics: list[Diagnostic]) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.CHT_TASK_BINDING_INVALID,
                f"{path} must be a non-negative integer.",
                path,
            )
        )
        return 0
    return value


def _require_positive_integer(value: Any, *, path: str, diagnostics: list[Diagnostic]) -> int:
    result = _require_non_negative_integer(value, path=path, diagnostics=diagnostics)
    if result == 0:
        diagnostics.append(
            _diagnostic(DiagnosticCode.CHT_TASK_BINDING_INVALID, f"{path} must be positive.", path)
        )
    return result


def load_cht_task_bindings(path: str | Path) -> CHTTaskBindingRegistry:
    binding_path = Path(path)
    try:
        payload = json.loads(binding_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CHTTaskLoweringError(
            [_diagnostic(DiagnosticCode.CHT_TASK_BINDING_INVALID, f"Could not load task bindings: {exc}", str(binding_path))]
        ) from exc
    return parse_cht_task_bindings(payload)


def parse_cht_task_bindings(payload: Any) -> CHTTaskBindingRegistry:
    diagnostics: list[Diagnostic] = []
    root = _require_object(payload, path="$", diagnostics=diagnostics)
    allowed_root = {"schema_version", "target_cht_version", "task_types"}
    for key in sorted(set(root) - allowed_root):
        diagnostics.append(
            _diagnostic(DiagnosticCode.CHT_TASK_BINDING_INVALID, f"Unknown root field '{key}'.", f"$.{key}")
        )
    schema_version = _require_string(root.get("schema_version"), path="$.schema_version", diagnostics=diagnostics)
    if schema_version and schema_version != CHT_TASK_BINDING_SCHEMA_VERSION:
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.CHT_TASK_BINDING_INVALID,
                f"Unsupported task-binding schema '{schema_version}'.",
                "$.schema_version",
            )
        )
    target_cht_version = _require_string(
        root.get("target_cht_version"), path="$.target_cht_version", diagnostics=diagnostics
    )
    task_type_payload = _require_object(root.get("task_types"), path="$.task_types", diagnostics=diagnostics)
    if not task_type_payload:
        diagnostics.append(
            _diagnostic(DiagnosticCode.CHT_TASK_BINDING_INVALID, "At least one task type is required.", "$.task_types")
        )

    task_types: dict[str, CHTTaskTypeBinding] = {}
    for logical_name, raw_binding in sorted(task_type_payload.items()):
        path = f"$.task_types.{logical_name}"
        logical = _require_string(logical_name, path=path, diagnostics=diagnostics, pattern=_SAFE_IDENTIFIER)
        value = _require_object(raw_binding, path=path, diagnostics=diagnostics)
        allowed = {
            "title_key",
            "source_message_key",
            "followup_form",
            "permission_key",
            "icon",
            "start_days",
            "end_days",
            "source_priority",
            "assignee_role",
            "priority",
        }
        for key in sorted(set(value) - allowed):
            diagnostics.append(
                _diagnostic(DiagnosticCode.CHT_TASK_BINDING_INVALID, f"Unknown task binding field '{key}'.", f"{path}.{key}")
            )
        priority_value = value.get("priority")
        priority: CHTTaskPriority | None = None
        if priority_value is not None:
            priority_object = _require_object(priority_value, path=f"{path}.priority", diagnostics=diagnostics)
            for key in sorted(set(priority_object) - {"level", "label"}):
                diagnostics.append(
                    _diagnostic(DiagnosticCode.CHT_TASK_BINDING_INVALID, f"Unknown priority field '{key}'.", f"{path}.priority.{key}")
                )
            priority = CHTTaskPriority(
                level=_require_positive_integer(
                    priority_object.get("level"), path=f"{path}.priority.level", diagnostics=diagnostics
                ),
                label=_require_string(
                    priority_object.get("label"),
                    path=f"{path}.priority.label",
                    diagnostics=diagnostics,
                    pattern=_SAFE_TRANSLATION_KEY,
                ),
            )
        assignee_role_value = value.get("assignee_role")
        assignee_role = None
        if assignee_role_value is not None:
            assignee_role = _require_string(
                assignee_role_value,
                path=f"{path}.assignee_role",
                diagnostics=diagnostics,
                pattern=_SAFE_ROLE,
            )
        source_priority_value = value.get("source_priority")
        source_priority = None
        if source_priority_value is not None:
            source_priority = _require_string(
                source_priority_value,
                path=f"{path}.source_priority",
                diagnostics=diagnostics,
                pattern=_SAFE_ROLE,
            )
        if logical:
            task_types[logical] = CHTTaskTypeBinding(
                logical_name=logical,
                source_message_key=_require_string(
                    value.get("source_message_key"),
                    path=f"{path}.source_message_key",
                    diagnostics=diagnostics,
                    pattern=_SAFE_MESSAGE_KEY,
                ),
                title_key=_require_string(
                    value.get("title_key"), path=f"{path}.title_key", diagnostics=diagnostics, pattern=_SAFE_TRANSLATION_KEY
                ),
                followup_form=_require_string(
                    value.get("followup_form"), path=f"{path}.followup_form", diagnostics=diagnostics, pattern=_SAFE_IDENTIFIER
                ),
                permission_key=_require_string(
                    value.get("permission_key"), path=f"{path}.permission_key", diagnostics=diagnostics, pattern=_SAFE_IDENTIFIER
                ),
                icon=_require_string(
                    value.get("icon"), path=f"{path}.icon", diagnostics=diagnostics, pattern=_SAFE_TRANSLATION_KEY
                ),
                start_days=_require_non_negative_integer(
                    value.get("start_days"), path=f"{path}.start_days", diagnostics=diagnostics
                ),
                end_days=_require_non_negative_integer(
                    value.get("end_days"), path=f"{path}.end_days", diagnostics=diagnostics
                ),
                source_priority=source_priority,
                assignee_role=assignee_role,
                priority=priority,
            )

    if diagnostics:
        raise CHTTaskLoweringError(diagnostics)
    reject_clinical_derivation(payload, context="CHT task binding registry")
    return CHTTaskBindingRegistry(
        schema_version=schema_version,
        target_cht_version=target_cht_version,
        task_types=task_types,
    )


def task_step(action_id: str) -> str:
    return action_id[2:] if action_id.startswith("a_") else action_id


def task_group_name(step: str) -> str:
    return f"task_intent_{step.replace('-', '_')}"


def task_rule_name(source_form_code: str, step: str) -> str:
    return f"chw-nav-{source_form_code.replace('_', '-')}-{step.replace('_', '-')}"


def resolve_static_due_in_days(document: ClinicalIRDocument, action: ActionDef) -> int | None:
    """Resolve a task interval only when the decision table makes it compile-time constant."""

    if action.due_in_days is not None:
        return action.due_in_days
    output_id = action.due_in_days_output
    if output_id is None:
        return None

    trigger_output = None
    if action.when is not None and action.when.get("kind") == "output":
        trigger_output = action.when.get("id")

    values: list[int] = []
    for decision in document.decisions.values():
        for rule in decision.rules:
            if trigger_output is not None:
                trigger = rule.then.get(str(trigger_output))
                if not (
                    isinstance(trigger, dict)
                    and trigger.get("kind") == "literal"
                    and trigger.get("value") is True
                ):
                    continue
            expression = rule.then.get(output_id)
            if not isinstance(expression, dict) or expression.get("kind") != "literal":
                return None
            value = expression.get("value")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return None
            values.append(value)

    return values[0] if values and len(set(values)) == 1 else None


def build_task_intent_plans(
    document: ClinicalIRDocument,
    *,
    source_form_code: str,
    bindings: CHTTaskBindingRegistry | None,
    required_calculations: dict[str, str],
) -> tuple[CHTTaskIntentPlan, ...]:
    actions = [action for action in document.actions.values() if action.kind == "create_task"]
    if not actions:
        return ()
    if bindings is None:
        raise CHTTaskLoweringError(
            [
                _diagnostic(
                    DiagnosticCode.CHT_TASK_TYPE_UNBOUND,
                    "Clinical IR contains create_task actions but no CHT task-binding registry was supplied.",
                    "actions",
                )
            ]
        )
    if _SAFE_IDENTIFIER.fullmatch(source_form_code) is None:
        raise CHTTaskLoweringError(
            [
                _diagnostic(
                    DiagnosticCode.CHT_TASK_BINDING_INVALID,
                    f"Source form code '{source_form_code}' is not a safe CHT form identifier.",
                    "metadata.guideline_id",
                )
            ]
        )

    diagnostics: list[Diagnostic] = []
    plans: list[CHTTaskIntentPlan] = []
    for action in actions:
        due_days = resolve_static_due_in_days(document, action)
        binding = bindings.task_types.get(action.task_type or "")
        if binding is None:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CHT_TASK_TYPE_UNBOUND,
                    f"Task type '{action.task_type}' has no CHT task binding.",
                    f"actions.{action.id}.task_type",
                )
            )
            continue
        if due_days is None or action.due_at_expr is not None:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CHT_TASK_SCHEDULE_UNSUPPORTED,
                    "CHT task lowering requires a non-negative static due_in_days or a "
                    "due_in_days_output that resolves to one value on every triggering rule; "
                    "due_at_expr is not lowered.",
                    f"actions.{action.id}",
                )
            )
            continue
        if action.assignee_role != binding.assignee_role:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CHT_TASK_SCHEDULE_UNSUPPORTED,
                    f"Action assignee_role '{action.assignee_role}' does not match binding role '{binding.assignee_role}'.",
                    f"actions.{action.id}.assignee_role",
                )
            )
            continue
        if action.priority != binding.source_priority:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CHT_TASK_SCHEDULE_UNSUPPORTED,
                    f"Action priority '{action.priority}' does not match binding source_priority '{binding.source_priority}'.",
                    f"actions.{action.id}.priority",
                )
            )
            continue
        if action.message_key != binding.source_message_key:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CHT_TASK_SCHEDULE_UNSUPPORTED,
                    f"Action message_key '{action.message_key}' does not match binding source_message_key '{binding.source_message_key}'.",
                    f"actions.{action.id}.message_key",
                )
            )
            continue
        step = task_step(action.id)
        if _SAFE_IDENTIFIER.fullmatch(step) is None:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CHT_TASK_BINDING_INVALID,
                    f"Action id '{action.id}' cannot produce a safe CHT task step.",
                    f"actions.{action.id}",
                )
            )
            continue
        group = task_group_name(step)
        name = task_rule_name(source_form_code, step)
        plans.append(
            CHTTaskIntentPlan(
                action_id=action.id,
                step=step,
                group=group,
                name=name,
                event_id=f"{name}-event",
                source_form_code=source_form_code,
                due_days=due_days,
                required_calculation=required_calculations[action.id],
                operation_id_calculation=f"concat(/data/meta/instanceID, '::{step}')",
                binding=binding,
                message_key=action.message_key,
            )
        )

    for attribute in ("group", "name", "event_id"):
        values = [getattr(plan, attribute) for plan in plans]
        duplicates = sorted({value for value in values if values.count(value) > 1})
        for duplicate in duplicates:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CHT_TASK_IDENTITY_COLLISION,
                    f"Multiple create_task actions lower to the same {attribute} '{duplicate}'.",
                    "actions",
                )
            )
    if diagnostics:
        raise CHTTaskLoweringError(diagnostics)
    return tuple(sorted(plans, key=lambda item: item.step))


def task_intent_rows(plan: CHTTaskIntentPlan) -> tuple[SurveyRow, ...]:
    binding = plan.binding
    rows = (
        SurveyRow(type="begin group", name=plan.group, appearance="hidden", role="task_intent_group"),
        SurveyRow(type="calculate", name="required", calculation=plan.required_calculation, role="task_intent"),
        SurveyRow(type="calculate", name="task_type", calculation=_xpath_string(binding.logical_name), role="task_intent"),
        SurveyRow(type="calculate", name="due_days", calculation=str(plan.due_days), role="task_intent"),
        SurveyRow(type="calculate", name="start_days", calculation=str(binding.start_days), role="task_intent"),
        SurveyRow(type="calculate", name="end_days", calculation=str(binding.end_days), role="task_intent"),
        SurveyRow(type="calculate", name="followup_form", calculation=_xpath_string(binding.followup_form), role="task_intent"),
        SurveyRow(type="calculate", name="operation_id", calculation=plan.operation_id_calculation, role="task_intent"),
        SurveyRow(type="calculate", name="local_write_intent", calculation="'submit_report'", role="task_intent"),
        SurveyRow(type="calculate", name="sync_observation", calculation="'not_observed'", role="task_intent"),
        SurveyRow(
            type="calculate",
            name="task_visibility_state",
            calculation="'pending_rule_evaluation'",
            role="task_intent",
        ),
        SurveyRow(type="end group", name=plan.group, role="task_intent_group"),
    )
    return rows


def _xpath_string(value: str) -> str:
    if "'" in value:
        raise CHTTaskLoweringError(
            [_diagnostic(DiagnosticCode.CHT_TASK_BINDING_INVALID, "XPath string values must not contain apostrophes.")]
        )
    return f"'{value}'"


def _js_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _priority_block(plan: CHTTaskIntentPlan) -> list[str]:
    if plan.binding.priority is None:
        return []
    return [
        "    priority: {",
        f"      level: {plan.binding.priority.level},",
        f"      label: {_js_string(plan.binding.priority.label)},",
        "    },",
    ]


def _task_definition(plan: CHTTaskIntentPlan) -> str:
    binding = plan.binding
    operation_path = f"{plan.group}.operation_id"
    required_path = f"{plan.group}.required"
    type_path = f"{plan.group}.task_type"
    return "\n".join(
        [
            "  {",
            f"    name: {_js_string(plan.name)},",
            f"    icon: {_js_string(binding.icon)},",
            f"    title: {_js_string(binding.title_key)},",
            "    appliesTo: 'reports',",
            f"    appliesToType: [{_js_string(plan.source_form_code)}],",
            "    appliesIf: function(contact, report) {",
            f"      const required = Utils.getField(report, {_js_string(required_path)});",
            f"      const taskType = Utils.getField(report, {_js_string(type_path)});",
            f"      const operationId = Utils.getField(report, {_js_string(operation_path)});",
            f"      return report && report.form === {_js_string(plan.source_form_code)} &&",
            f"        isTrue(required) && taskType === {_js_string(binding.logical_name)} &&",
            f"        isValidOperationId(operationId) && isCanonicalIntent(contact, report, {_js_string(operation_path)}, {_js_string(plan.source_form_code)});",
            "    },",
            "    actions: [{",
            f"      form: {_js_string(binding.followup_form)},",
            "      modifyContent: function(content, contact, report, event) {",
            f"        content.source_task_operation_id = Utils.getField(report, {_js_string(operation_path)});",
            "        content.source_task_event_id = event.id;",
            "      },",
            "    }],",
            "    events: [{",
            f"      id: {_js_string(plan.event_id)},",
            f"      days: {plan.due_days},",
            f"      start: {binding.start_days},",
            f"      end: {binding.end_days},",
            "    }],",
            *_priority_block(plan),
            "    resolvedIf: function(contact, report, event, dueDate) {",
            f"      const operationId = Utils.getField(report, {_js_string(operation_path)});",
            f"      if (!isValidReport(report, {_js_string(plan.source_form_code)}) || !isValidOperationId(operationId) ||",
            "          !event || !isNonNegativeInteger(event.start) || !isNonNegativeInteger(event.end) ||",
            "          !(dueDate instanceof Date) || !Number.isFinite(dueDate.getTime())) return false;",
            "      const startDate = Utils.addDate(dueDate, -event.start);",
            "      const endDate = Utils.addDate(dueDate, event.end + 1);",
            "      if (!(startDate instanceof Date) || !(endDate instanceof Date)) return false;",
            "      const start = startDate.getTime();",
            "      const end = endDate.getTime();",
            "      if (!Number.isFinite(start) || !Number.isFinite(end) || start >= end) return false;",
            "      return safeReports(contact).some(function(candidate) {",
            f"        return isValidReport(candidate, {_js_string(binding.followup_form)}) &&",
            "          Utils.getField(candidate, 'source_task_operation_id') === operationId &&",
            "          Utils.getField(candidate, 'source_task_event_id') === event.id &&",
            "          candidate.reported_date >= start && candidate.reported_date < end;",
            "      });",
            "    },",
            "  }",
        ]
    )


def generate_tasks_js(plans: tuple[CHTTaskIntentPlan, ...] | list[CHTTaskIntentPlan]) -> str:
    if not plans:
        return ""
    ordered = sorted(plans, key=lambda item: item.step)
    source = "\n".join(
        [
            "'use strict';",
            "",
            "// Generated by CHW Navigator. Do not edit derived rules by hand.",
            "// Task documents are generated by CHT Core from stored task-intent report fields.",
            "",
            "const OPERATION_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:@\\/-]{0,127}::[a-z][a-z0-9_-]{0,127}$/;",
            "const DOCUMENT_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:@\\/-]{0,255}$/;",
            "",
            "function isNonNegativeInteger(value) {",
            "  return Number.isInteger(value) && value >= 0;",
            "}",
            "",
            "function isTrue(value) {",
            "  return value === true || value === 'true' || value === 1 || value === '1';",
            "}",
            "",
            "function isValidOperationId(value) {",
            "  return typeof value === 'string' && OPERATION_ID_PATTERN.test(value);",
            "}",
            "",
            "function isValidDocumentId(value) {",
            "  return typeof value === 'string' && DOCUMENT_ID_PATTERN.test(value);",
            "}",
            "",
            "function safeReports(contact) {",
            "  return contact && Array.isArray(contact.reports) ? contact.reports : [];",
            "}",
            "",
            "function isValidReport(report, expectedForm) {",
            "  return Boolean(report) && report.form === expectedForm && isValidDocumentId(report._id) &&",
            "    Number.isFinite(report.reported_date) && report.reported_date > 0;",
            "}",
            "",
            "function isCanonicalIntent(contact, report, operationPath, sourceForm) {",
            "  if (!isValidReport(report, sourceForm)) return false;",
            "  const operationId = Utils.getField(report, operationPath);",
            "  if (!isValidOperationId(operationId)) return false;",
            "  const matches = safeReports(contact)",
            "    .filter(function(candidate) {",
            "      return isValidReport(candidate, sourceForm) && Utils.getField(candidate, operationPath) === operationId;",
            "    })",
            "    .slice()",
            "    .sort(function(left, right) {",
            "      const byDate = left.reported_date - right.reported_date;",
            "      return byDate !== 0 ? byDate : left._id.localeCompare(right._id);",
            "    });",
            "  return matches.length > 0 && matches[0]._id === report._id;",
            "}",
            "",
            "module.exports = [",
            ",\n".join(_task_definition(plan) for plan in ordered),
            "];",
            "",
        ]
    )
    reject_clinical_derivation(source, context="generated CHT tasks.js")
    return source


def task_plan_payload(plan: CHTTaskIntentPlan) -> dict[str, Any]:
    return {
        "action_id": plan.action_id,
        "step": plan.step,
        "group": plan.group,
        "name": plan.name,
        "event_id": plan.event_id,
        "source_form_code": plan.source_form_code,
        "due_days": plan.due_days,
        "required_calculation": plan.required_calculation,
        "operation_id_calculation": plan.operation_id_calculation,
        "message_key": plan.message_key,
        "binding": asdict(plan.binding),
    }


def sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
