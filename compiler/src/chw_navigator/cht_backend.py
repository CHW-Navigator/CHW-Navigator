from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

from .clinical_ir import ClinicalIRDocument
from .form_ir import SurveyRow
from .xlsform_backend import BuiltXLSForm, build_xlsform


@dataclass(slots=True)
class CHTProfile:
    name: str = "cht-default"
    inject_today: bool = True
    today_row_name: str = "st_today"
    yes_no_horizontal: bool = True
    classification_note_appearance: str = "critical-alert"
    symptom_group_appearance: str = "field-list"


@dataclass(slots=True)
class CHTAppearanceOverride:
    row_name: str
    appearance: str
    reason: str


@dataclass(slots=True)
class CHTReadHistoryRequest:
    action_id: str
    source: str
    outputs: list[str] = field(default_factory=list)
    mappings: list[dict[str, str]] = field(default_factory=list)
    fail_mode: str | None = None


@dataclass(slots=True)
class CHTTaskSpec:
    action_id: str
    task_type: str
    trigger_expr: dict[str, object] | None = None
    due_in_days: int | None = None
    priority: str | None = None
    assignee_role: str | None = None
    message_key: str | None = None


@dataclass(slots=True)
class CHTLoweringPlan:
    profile: CHTProfile
    today_row: SurveyRow | None = None
    appearance_overrides: list[CHTAppearanceOverride] = field(default_factory=list)
    read_history_requests: list[CHTReadHistoryRequest] = field(default_factory=list)
    task_specs: list[CHTTaskSpec] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CHTAdapterArtifacts:
    output_dir: Path
    plan_json_path: Path
    history_stub_path: Path
    tasks_stub_path: Path
    readme_path: Path


def default_cht_profile() -> CHTProfile:
    return CHTProfile()


def build_cht_lowering_plan(
    document: ClinicalIRDocument,
    built: BuiltXLSForm | None = None,
    *,
    profile: CHTProfile | None = None,
) -> CHTLoweringPlan:
    active_profile = profile or default_cht_profile()
    workbook = built or build_xlsform(document)
    plan = CHTLoweringPlan(profile=active_profile)

    if active_profile.inject_today:
        plan.today_row = SurveyRow(
            type="calculate",
            name=active_profile.today_row_name,
            calculation="today()",
            role="system_today",
        )

    if active_profile.yes_no_horizontal:
        for row in workbook.workbook.survey:
            if row.type == "select_one yes_no":
                plan.appearance_overrides.append(
                    CHTAppearanceOverride(
                        row_name=row.name,
                        appearance="horizontal",
                        reason="CHT default for binary yes/no questions",
                    )
                )

    for row in workbook.workbook.survey:
        if row.type == "note" and row.role in {"message", "guidance"}:
            plan.appearance_overrides.append(
                CHTAppearanceOverride(
                    row_name=row.name,
                    appearance=active_profile.classification_note_appearance,
                    reason="CHT default for classification and recommendation notes",
                )
            )

    for action in document.actions.values():
        if action.kind == "read_history":
            plan.read_history_requests.append(
                CHTReadHistoryRequest(
                    action_id=action.id,
                    source=action.source or "cht",
                    outputs=list(action.outputs),
                    mappings=[
                        {
                            "record_key": mapping.record_key,
                            "target_var": mapping.target_var,
                            **(
                                {"recorded_at_target_var": mapping.recorded_at_target_var}
                                if mapping.recorded_at_target_var is not None
                                else {}
                            ),
                        }
                        for mapping in action.mappings
                    ],
                    fail_mode=action.fail_mode,
                )
            )
        if action.kind == "create_task":
            plan.task_specs.append(
                CHTTaskSpec(
                    action_id=action.id,
                    task_type=action.task_type or "unspecified_task",
                    trigger_expr=action.when,
                    due_in_days=action.due_in_days,
                    priority=action.priority,
                    assignee_role=action.assignee_role,
                    message_key=action.message_key,
                )
            )

    plan.notes.append(
        "Symptom-group field-list layout is a CHT form-construction convention and is not yet derived automatically from canonical Clinical IR."
    )
    plan.notes.append(
        "read_history lowering is represented as a backend plan only; direct CHT code generation still needs an adapter implementation."
    )
    return plan


def render_cht_adapter_stub(plan: CHTLoweringPlan) -> dict[str, object]:
    return {
        "profile": {
            "name": plan.profile.name,
            "today_row_name": plan.profile.today_row_name,
            "yes_no_horizontal": plan.profile.yes_no_horizontal,
            "classification_note_appearance": plan.profile.classification_note_appearance,
            "symptom_group_appearance": plan.profile.symptom_group_appearance,
        },
        "today_row": (
            {
                "type": plan.today_row.type,
                "name": plan.today_row.name,
                "calculation": plan.today_row.calculation,
                "role": plan.today_row.role,
            }
            if plan.today_row is not None
            else None
        ),
        "appearance_overrides": [
            {
                "row_name": item.row_name,
                "appearance": item.appearance,
                "reason": item.reason,
            }
            for item in plan.appearance_overrides
        ],
        "read_history_adapter": {
            "requests": [
                {
                    "action_id": item.action_id,
                    "source": item.source,
                    "outputs": item.outputs,
                    "mappings": item.mappings,
                    "fail_mode": item.fail_mode,
                }
                for item in plan.read_history_requests
            ],
            "status": "stub_only",
        },
        "task_adapter": {
            "tasks": [
                {
                    "action_id": item.action_id,
                    "task_type": item.task_type,
                    "trigger_expr": item.trigger_expr,
                    "due_in_days": item.due_in_days,
                    "priority": item.priority,
                    "assignee_role": item.assignee_role,
                    "message_key": item.message_key,
                }
                for item in plan.task_specs
            ],
            "status": "stub_only",
        },
        "notes": list(plan.notes),
    }


def write_cht_adapter_stub(plan: CHTLoweringPlan, output_dir: str | Path) -> CHTAdapterArtifacts:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    payload = render_cht_adapter_stub(plan)
    plan_json_path = target_dir / "cht_lowering_plan.json"
    history_stub_path = target_dir / "cht_read_history_stub.json"
    tasks_stub_path = target_dir / "cht_task_stub.json"
    readme_path = target_dir / "README.md"

    plan_json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    history_stub_path.write_text(
        json.dumps(payload["read_history_adapter"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tasks_stub_path.write_text(
        json.dumps(payload["task_adapter"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    readme_path.write_text(
        "\n".join(
            [
                "# CHT Adapter Stub",
                "",
                "This folder contains non-executable adapter stubs derived from the CHT lowering plan.",
                "",
                "Files:",
                "",
                "- `cht_lowering_plan.json`: full lowering plan",
                "- `cht_read_history_stub.json`: history-read adapter inputs",
                "- `cht_task_stub.json`: task adapter inputs",
                "",
                "These are planning artifacts only. They are intended to make integration requirements explicit before production CHT code generation exists.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return CHTAdapterArtifacts(
        output_dir=target_dir,
        plan_json_path=plan_json_path,
        history_stub_path=history_stub_path,
        tasks_stub_path=tasks_stub_path,
        readme_path=readme_path,
    )
