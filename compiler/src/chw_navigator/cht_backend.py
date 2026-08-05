from __future__ import annotations

import copy
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path

from .clinical_ir import ClinicalIRDocument
from .cht_local_data import (
    CHTFormContext,
    CHTLocalDataLoweringError,
    CHTLocalDataReadPlan,
    CHTLocalDataRegistry,
    lower_cht_local_data_reads,
)
from .cht_special_functions import (
    CHTSpecialFunctionBundle,
    lower_reviewed_special_functions,
    write_cht_special_function_bundle,
)
from .cht_tasks import (
    CHTTaskBindingRegistry,
    CHTTaskIntentPlan,
    CHTTaskLoweringError,
    build_task_intent_plans,
    generate_tasks_js,
    task_intent_rows,
    task_plan_payload,
)
from .cht_xform import generate_cht_xform
from .diagnostics import Diagnostic, DiagnosticCode
from .form_ir import SurveyRow
from .xlsform_backend import BuiltXLSForm, build_xlsform, compile_xlsform_expression, write_xlsform_csvs


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
    local_data_reads: tuple[CHTLocalDataReadPlan, ...] = ()
    local_data_registry: CHTLocalDataRegistry | None = None
    form_context: CHTFormContext | None = None
    task_specs: list[CHTTaskSpec] = field(default_factory=list)
    task_intent_plans: tuple[CHTTaskIntentPlan, ...] = ()
    cht_xlsform: BuiltXLSForm | None = None
    target_cht_version: str | None = None
    special_function_bundle: CHTSpecialFunctionBundle | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CHTAdapterArtifacts:
    output_dir: Path
    plan_json_path: Path
    history_stub_path: Path
    task_plan_path: Path
    readme_path: Path
    manifest_path: Path
    tasks_js_path: Path | None = None
    form_survey_path: Path | None = None
    form_choices_path: Path | None = None
    form_source_map_path: Path | None = None
    form_xform_path: Path | None = None
    legacy_history_stub_path: Path | None = None
    special_function_paths: tuple[Path, ...] = ()

    @property
    def tasks_stub_path(self) -> Path:
        """Compatibility alias for callers written before executable task lowering."""

        return self.task_plan_path


def default_cht_profile() -> CHTProfile:
    return CHTProfile()


def build_cht_lowering_plan(
    document: ClinicalIRDocument,
    built: BuiltXLSForm | None = None,
    *,
    profile: CHTProfile | None = None,
    task_bindings: CHTTaskBindingRegistry | None = None,
    local_data_registry: CHTLocalDataRegistry | None = None,
    form_context: CHTFormContext = "contact",
    special_function_target_cht_version: str | None = None,
) -> CHTLoweringPlan:
    active_profile = profile or default_cht_profile()
    workbook = built or build_xlsform(document)
    plan = CHTLoweringPlan(profile=active_profile, cht_xlsform=copy.deepcopy(workbook))

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

    required_calculations: dict[str, str] = {}
    for action in document.actions.values():
        if action.kind in {"read_history", "read_local_data"} and local_data_registry is None:
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
            required_calculations[action.id] = (
                "true()"
                if action.when is None
                else f"if({compile_xlsform_expression(action.when, document, output_rows=workbook.output_row_names)}, true(), false())"
            )
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

    if task_bindings is not None:
        from .cht_special_functions import reviewed_cht_profile

        reviewed_cht_profile(task_bindings.target_cht_version)
        if (
            special_function_target_cht_version is not None
            and task_bindings.target_cht_version != special_function_target_cht_version
        ):
            raise CHTTaskLoweringError(
                [
                    Diagnostic(
                        code=DiagnosticCode.CHT_TASK_BINDING_INVALID,
                        severity="error",
                        message=(
                            "Task bindings and special functions target different CHT versions: "
                            f"{task_bindings.target_cht_version} versus {special_function_target_cht_version}."
                        ),
                        path="target_cht_version",
                    )
                ]
            )
        plan.target_cht_version = task_bindings.target_cht_version
    if local_data_registry is not None:
        from .cht_special_functions import reviewed_cht_profile

        reviewed_cht_profile(local_data_registry.target_cht_version)
        if plan.target_cht_version is not None and plan.target_cht_version != local_data_registry.target_cht_version:
            raise CHTLocalDataLoweringError(
                [
                    Diagnostic(
                        code=DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID,
                        severity="error",
                        message=(
                            "Task bindings and local-data bindings target different CHT versions: "
                            f"{plan.target_cht_version} versus {local_data_registry.target_cht_version}."
                        ),
                        path="target_cht_version",
                    )
                ]
            )
        plan.target_cht_version = local_data_registry.target_cht_version
        plan.local_data_registry = local_data_registry
        plan.form_context = form_context
        if plan.cht_xlsform is None:
            raise AssertionError("Local-data lowering requires the matching XLSForm source.")
        plan.local_data_reads = lower_cht_local_data_reads(
            document,
            plan.cht_xlsform,
            local_data_registry,
            form_context=form_context,
        )
    plan.task_intent_plans = build_task_intent_plans(
        document,
        source_form_code=workbook.workbook.form_id,
        bindings=task_bindings,
        required_calculations=required_calculations,
    )
    if plan.cht_xlsform is not None:
        for task_plan in plan.task_intent_plans:
            plan.cht_xlsform.workbook.survey.extend(task_intent_rows(task_plan))
            plan.cht_xlsform.row_sources[task_plan.group] = [
                item
                for source in document.actions[task_plan.action_id].provenance
                for item in [
                    {
                        "source_id": source.source_id,
                        **({"location": source.location} if source.location is not None else {}),
                        **({"note": source.note} if source.note is not None else {}),
                    }
                ]
            ]

    plan.notes.append(
        "Symptom-group field-list layout is a CHT form-construction convention and is not yet derived automatically from canonical Clinical IR."
    )
    if plan.read_history_requests:
        plan.notes.append(
            "Unregistered read_history remains a plan; supply a versioned local-data binding registry to generate CHT form reads."
        )
    if plan.local_data_reads:
        plan.notes.append(
            "Registered local-data reads are lowered to context-specific CHT form inputs with explicit availability status and failure behavior."
        )
    if plan.task_intent_plans:
        plan.notes.append(
            "create_task actions are lowered into stored form fields and deterministic report-based tasks.js rules compatible with the reviewed TypeScript composer."
        )
    if special_function_target_cht_version is not None:
        plan.target_cht_version = special_function_target_cht_version
        plan.special_function_bundle = lower_reviewed_special_functions(special_function_target_cht_version)
        plan.notes.append(
            "Reviewed technical special functions are emitted as executable CHT XForms and an extension library; they do not derive clinical policy."
        )
    return plan


def render_cht_adapter_plan(plan: CHTLoweringPlan) -> dict[str, object]:
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
            "status": (
                "generated"
                if plan.local_data_reads
                else "stub_only"
                if plan.read_history_requests
                else "not_requested"
            ),
            "schema_version": (
                plan.local_data_registry.schema_version if plan.local_data_registry is not None else None
            ),
            "target_cht_version": (
                plan.local_data_registry.target_cht_version
                if plan.local_data_registry is not None
                else None
            ),
            "form_context": plan.form_context,
            "generated_reads": [
                {
                    "action_id": item.action_id,
                    "binding_id": item.binding_id,
                    "target_var": item.target_var,
                    "source_xpath": item.source_xpath,
                    "recorded_at_xpath": item.recorded_at_xpath,
                    "status_row": item.status_row,
                    "fallback_row": item.fallback_row,
                    "fail_mode": item.fail_mode,
                    "freshness_policy": item.freshness_policy,
                }
                for item in plan.local_data_reads
            ],
        },
        "task_adapter": {
            "tasks": [task_plan_payload(item) for item in plan.task_intent_plans],
            "status": "generated" if plan.task_intent_plans else "not_requested",
            "target_cht_version": plan.target_cht_version,
            "tasks_path": "tasks.js" if plan.task_intent_plans else None,
            "source_form_code": (
                plan.task_intent_plans[0].source_form_code if plan.task_intent_plans else None
            ),
        },
        "special_function_adapter": (
            {
                "status": "generated",
                "target_cht_version": plan.special_function_bundle.profile.cht_version,
                "files": [
                    {"path": artifact.path, "sha256": artifact.sha256}
                    for artifact in plan.special_function_bundle.files
                ],
                "diagnostics": [
                    {
                        "code": diagnostic.code,
                        "severity": diagnostic.severity,
                        "message": diagnostic.message,
                        **({"path": diagnostic.path} if diagnostic.path is not None else {}),
                    }
                    for diagnostic in plan.special_function_bundle.diagnostics
                ],
            }
            if plan.special_function_bundle is not None
            else {"status": "not_requested"}
        ),
        "notes": list(plan.notes),
    }


def write_cht_adapter_bundle(plan: CHTLoweringPlan, output_dir: str | Path) -> CHTAdapterArtifacts:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    payload = render_cht_adapter_plan(plan)
    plan_json_path = target_dir / "cht_lowering_plan.json"
    history_stub_path = target_dir / "cht_local_data_plan.json"
    legacy_history_stub_path = target_dir / "cht_read_history_stub.json"
    task_plan_path = target_dir / "cht_task_plan.json"
    readme_path = target_dir / "README.md"
    manifest_path = target_dir / "cht-bundle-manifest.json"
    if plan.special_function_bundle is not None:
        write_cht_special_function_bundle(plan.special_function_bundle, target_dir)
        special_function_paths = tuple(
            [target_dir / artifact.path for artifact in plan.special_function_bundle.files]
            + [target_dir / "special-function-manifest.json"]
        )
    else:
        special_function_paths = ()

    plan_json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    history_stub_path.write_text(
        json.dumps(payload["read_history_adapter"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    legacy_history_stub_path.write_text(
        history_stub_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    task_plan_path.write_text(
        json.dumps(payload["task_adapter"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tasks_js_path: Path | None = None
    form_survey_path: Path | None = None
    form_choices_path: Path | None = None
    form_source_map_path: Path | None = None
    form_xform_path: Path | None = None
    if plan.task_intent_plans or plan.local_data_reads:
        if plan.cht_xlsform is None:
            raise ValueError("CHT executable plans require the matching CHT XLSForm source.")
        if plan.task_intent_plans:
            tasks_js_path = target_dir / "tasks.js"
            tasks_js_path.write_text(generate_tasks_js(plan.task_intent_plans), encoding="utf-8")
        form_code = (
            plan.task_intent_plans[0].source_form_code
            if plan.task_intent_plans
            else plan.cht_xlsform.workbook.form_id
        )
        form_source_dir = target_dir / "forms" / "app" / f"{form_code}.xlsform"
        survey, choices, source_map = write_xlsform_csvs(plan.cht_xlsform, str(form_source_dir))
        form_survey_path = Path(survey)
        form_choices_path = Path(choices)
        form_source_map_path = Path(source_map)
        if plan.local_data_reads:
            form_xform_path = target_dir / "forms" / "app" / f"{form_code}.xml"
            form_xform_path.write_text(generate_cht_xform(plan.cht_xlsform), encoding="utf-8")

    manifest_files = [
        path
        for path in (
            plan_json_path,
            history_stub_path,
            legacy_history_stub_path,
            task_plan_path,
            tasks_js_path,
            form_survey_path,
            form_choices_path,
            form_source_map_path,
            form_xform_path,
            *special_function_paths,
        )
        if path is not None
    ]
    manifest = {
        "schema_version": "cht-compiler-bundle@1.0.0",
        "target_cht_version": plan.target_cht_version,
        "task_binding_schema_version": (
            "cht-task-bindings@1.0.0" if plan.task_intent_plans else None
        ),
        "local_data_binding_schema_version": (
            plan.local_data_registry.schema_version if plan.local_data_registry is not None else None
        ),
        "form_context": plan.form_context,
        "task_composer_contract": (
            "@chw-navigator/cht-integration task-composer@1" if plan.task_intent_plans else None
        ),
        "deployment_requirements": {
            "permissions": sorted({item.binding.permission_key for item in plan.task_intent_plans}),
            "translation_keys": sorted(
                {item.binding.title_key for item in plan.task_intent_plans}
                | {
                    item.binding.priority.label
                    for item in plan.task_intent_plans
                    if item.binding.priority is not None
                }
            ),
            "icons": sorted({item.binding.icon for item in plan.task_intent_plans}),
            "followup_forms": sorted({item.binding.followup_form for item in plan.task_intent_plans}),
            "assignee_roles": sorted(
                {
                    item.binding.assignee_role
                    for item in plan.task_intent_plans
                    if item.binding.assignee_role is not None
                }
            ),
        },
        "files": [
            {
                "path": path.relative_to(target_dir).as_posix(),
                "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in sorted(manifest_files)
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    readme_path.write_text(
        "\n".join(
            [
                "# CHT Compiler Bundle",
                "",
                "This folder contains CHT artifacts derived from one Clinical IR document.",
                "",
                "Files:",
                "",
                "- `cht_lowering_plan.json`: full lowering plan",
                "- `cht_local_data_plan.json`: registered generated reads or unimplemented legacy history-read requests",
                "- `cht_read_history_stub.json`: compatibility copy of the local-data plan for older bundle consumers",
                "- `cht_task_plan.json`: resolved task types and task-rule identities",
                *(
                    [
                        "- `tasks.js`: executable report-based CHT task rules",
                        "- `forms/app/<form>.xlsform/`: survey/choices source with the exact task-intent fields read by `tasks.js`",
                    ]
                    if plan.task_intent_plans
                    else []
                ),
                *(
                    ["- `forms/app/<form>.xml`: executable CHT XForm containing the registered local-data reads"]
                    if plan.local_data_reads
                    else []
                ),
                *(
                    [
                        "- `special-function-manifest.json`: reviewed target profile, diagnostics, and hashes",
                        "- `forms/app/technical_*.xml`: executable technical special-function XForms",
                        "- `extension-libs/gestational-age-from-lmp.js`: dependency-free CHT extension library",
                    ]
                    if plan.special_function_bundle is not None
                    else []
                ),
                "",
                "Task rules and registered local-data form reads are executable candidates. Convert and test the accompanying XLSForm in the reviewed CHT build pipeline before deployment. Unregistered legacy history reads remain unimplemented. Special-function files, when present, also require official-harness and target-runtime evidence.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return CHTAdapterArtifacts(
        output_dir=target_dir,
        plan_json_path=plan_json_path,
        history_stub_path=history_stub_path,
        task_plan_path=task_plan_path,
        readme_path=readme_path,
        manifest_path=manifest_path,
        tasks_js_path=tasks_js_path,
        form_survey_path=form_survey_path,
        form_choices_path=form_choices_path,
        form_source_map_path=form_source_map_path,
        form_xform_path=form_xform_path,
        legacy_history_stub_path=legacy_history_stub_path,
        special_function_paths=special_function_paths,
    )


def write_cht_adapter_stub(plan: CHTLoweringPlan, output_dir: str | Path) -> CHTAdapterArtifacts:
    """Compatibility wrapper; new code should call write_cht_adapter_bundle."""

    return write_cht_adapter_bundle(plan, output_dir)


def render_cht_adapter_stub(plan: CHTLoweringPlan) -> dict[str, object]:
    """Compatibility wrapper; new code should call render_cht_adapter_plan."""

    return render_cht_adapter_plan(plan)
