from __future__ import annotations

from dataclasses import dataclass
import ast
import copy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .canonical_bridge import (
    RESOLUTION_FORBIDDEN_SELECTORS,
    RESOLUTION_LOCK_SCHEMA_VERSION,
    RESOLUTION_MATCHED_FIELDS,
    RESOLUTION_RULE_VERSION,
)
from .cht_backend import CHTAdapterArtifacts, build_cht_lowering_plan, write_cht_adapter_bundle
from .cht_evidence import default_runner_records
from .cht_local_data import CHTLocalDataRegistry, load_cht_local_data_registry
from .cht_special_functions import CHTSpecialFunctionBundle, GeneratedCHTFile, naegele_extension_source, reviewed_cht_profile
from .cht_task_composer import CHTTaskCompositionError, compose_tasks_js
from .cht_tasks import CHTTaskBindingRegistry, load_cht_task_bindings
from .clinical_ir import ClinicalIRDocument
from .diagnostics import Diagnostic, DiagnosticCode
from .form_ir import SurveyRow
from .queued_topology import QueuedOperation, TopologySnapshot
from .registry_governance import ActivatedRegistryRelease, RegistrySetV2, load_registry_set_v2
from .registry_set import Capability, TargetProfile, content_digest
from .special_functions import NAEGELE_FUNCTION_VERSION, NAEGELE_REFERENCE_VERSION, sha256_text
from .validator import validate_document


CHT_RUNTIME_BINDINGS_SCHEMA_VERSION = "cht-runtime-bindings@1.0.0"
_SAFE_ROW = re.compile(r"^[a-z][a-z0-9_]{0,127}$")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CHTRuntimeVariableBinding(_StrictModel):
    variable_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,127}$")
    calculation: str = Field(min_length=1)
    bind_type: Literal["string", "int", "decimal", "date", "dateTime"]
    role: str = Field(pattern=r"^[a-z][a-z0-9_]{0,127}$")


class CHTRuntimeBindingRegistry(_StrictModel):
    schema_version: Literal[CHT_RUNTIME_BINDINGS_SCHEMA_VERSION]
    content_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    target_profile_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    target_cht_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    bindings: tuple[CHTRuntimeVariableBinding, ...]

    @model_validator(mode="after")
    def variable_ids_are_unique(self) -> "CHTRuntimeBindingRegistry":
        values = [item.variable_id for item in self.bindings]
        if len(values) != len(set(values)):
            raise ValueError("duplicate runtime variable bindings are forbidden")
        return self


@dataclass(frozen=True, slots=True)
class ReviewedCapabilityLowerer:
    python_module: str
    python_symbol: str
    cht_extension_module: str
    function_version: str
    reference_version: str
    source: str


@dataclass(frozen=True, slots=True)
class CHTProductionBuild:
    output_dir: Path
    adapter: CHTAdapterArtifacts
    composed_tasks_path: Path
    rollback_tasks_path: Path
    evidence_manifest_path: Path
    deterministic: dict[str, Any]


class CHTProductionError(ValueError):
    def __init__(self, diagnostics: list[Diagnostic] | tuple[Diagnostic, ...]):
        self.diagnostics = tuple(diagnostics)
        super().__init__(
            "CHT production build failed closed:\n"
            + "\n".join(f"{item.code}: {item.message}" for item in self.diagnostics)
        )


_REVIEWED_LOWERERS = {
    (
        "chw_navigator.special_functions",
        "calculate_gestational_age_naegele",
        "gestational-age-from-lmp.js",
    ): ReviewedCapabilityLowerer(
        python_module="chw_navigator.special_functions",
        python_symbol="calculate_gestational_age_naegele",
        cht_extension_module="gestational-age-from-lmp.js",
        function_version=NAEGELE_FUNCTION_VERSION,
        reference_version=NAEGELE_REFERENCE_VERSION,
        source=naegele_extension_source(),
    )
}


def _diagnostic(code: DiagnosticCode, message: str, path: str | None = None) -> Diagnostic:
    return Diagnostic(code=code, severity="error", message=message, path=path)


def _load_json(path: str | Path) -> Any:
    source = Path(path)
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CHTProductionError(
            [_diagnostic(DiagnosticCode.PRODUCT_CONTRACT_INVALID, f"Could not load {source}: {exc}", str(source))]
        ) from exc


def seal_runtime_bindings(payload: dict[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(payload)
    sealed["bindings"] = sorted(sealed.get("bindings", []), key=lambda item: item.get("variable_id", ""))
    sealed["content_digest"] = content_digest(sealed)
    return sealed


def parse_runtime_bindings(payload: Any) -> CHTRuntimeBindingRegistry:
    try:
        document = CHTRuntimeBindingRegistry.model_validate(payload)
    except ValidationError as exc:
        raise CHTProductionError(
            [
                _diagnostic(
                    DiagnosticCode.CHT_RUNTIME_BINDING_INVALID,
                    str(item["msg"]),
                    "$" + "".join(
                        f"[{part}]" if isinstance(part, int) else f".{part}" for part in item["loc"]
                    ),
                )
                for item in exc.errors(include_url=False)
            ]
        ) from exc
    expected = seal_runtime_bindings(document.model_dump(mode="json"))["content_digest"]
    if document.content_digest != expected:
        raise CHTProductionError(
            [_diagnostic(DiagnosticCode.CHT_RUNTIME_BINDING_INVALID, "Runtime-binding digest does not match.", "$.content_digest")]
        )
    return document


def load_runtime_bindings(path: str | Path) -> CHTRuntimeBindingRegistry:
    return parse_runtime_bindings(_load_json(path))


def _literal_values(expression: Any) -> set[str]:
    if isinstance(expression, dict):
        values = {
            str(expression["value"])
            for _ in [0]
            if expression.get("kind") == "literal" and isinstance(expression.get("value"), str)
        }
        for value in expression.values():
            values.update(_literal_values(value))
        return values
    if isinstance(expression, list):
        return {item for value in expression for item in _literal_values(value)}
    return set()


def _references_variable(expression: Any, variable_id: str) -> bool:
    if isinstance(expression, dict):
        if expression.get("kind") == "var" and expression.get("id") == variable_id:
            return True
        return any(_references_variable(value, variable_id) for value in expression.values())
    if isinstance(expression, list):
        return any(_references_variable(value, variable_id) for value in expression)
    return False


def validate_capability_invocations(
    document: ClinicalIRDocument,
    capabilities: dict[str, Capability],
) -> tuple[Capability, ...]:
    diagnostics: list[Diagnostic] = []
    referenced: list[Capability] = []
    seen_capability_ids: set[str] = set()
    for action in sorted(document.actions.values(), key=lambda item: item.id):
        if action.kind != "invoke_capability":
            continue
        capability = capabilities.get(action.capability_id or "")
        if capability is None:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CAPABILITY_REFERENCE_UNRESOLVED,
                    f"Capability '{action.capability_id}' is not in the active registry.",
                    f"actions.{action.id}.capability_id",
                )
            )
            continue
        if capability.id in seen_capability_ids:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CAPABILITY_INVOCATION_INVALID,
                    f"Bounded Release 1 lowering permits one invocation of capability '{capability.id}' per document.",
                    f"actions.{action.id}.capability_id",
                )
            )
            continue
        seen_capability_ids.add(capability.id)
        expected_inputs = [item.name for item in capability.inputs]
        expected_outputs = [item.name for item in capability.outputs]
        if list(action.arguments) != expected_inputs:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CAPABILITY_INVOCATION_INVALID,
                    "Capability arguments must match the registered order.",
                    f"actions.{action.id}.arguments",
                )
            )
        if [item.record_key for item in action.mappings] != expected_outputs:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CAPABILITY_INVOCATION_INVALID,
                    "Capability output mappings must match the registered order.",
                    f"actions.{action.id}.mappings",
                )
            )
        covered: set[str] = set()
        for decision in document.decisions.values():
            for rule in decision.rules:
                if action.status_target_var and _references_variable(rule.when, action.status_target_var):
                    covered.update(_literal_values(rule.when))
        missing = sorted(set(capability.status_set) - covered)
        if missing:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.STATUS_COVERAGE_INCOMPLETE,
                    "Capability caller is missing explicit status branches: " + ", ".join(missing) + ".",
                    "decisions",
                )
            )
        referenced.append(capability)
    if diagnostics:
        raise CHTProductionError(diagnostics)
    return tuple(referenced)


def _replace_row(
    plan: Any,
    variable_id: str,
    *,
    calculation: str,
    bind_type: str,
    role: str,
) -> None:
    row = next((item for item in plan.cht_xlsform.workbook.survey if item.name == variable_id), None)
    if row is None:
        raise CHTProductionError(
            [_diagnostic(DiagnosticCode.CHT_RUNTIME_BINDING_INVALID, f"Runtime variable '{variable_id}' is absent.")]
        )
    row.type = "calculate"
    row.label = ""
    row.required = ""
    row.calculation = calculation
    row.bind_type = bind_type
    row.role = role


def apply_runtime_bindings(
    plan: Any,
    document: ClinicalIRDocument,
    bindings: CHTRuntimeBindingRegistry,
    target_profile: TargetProfile,
) -> None:
    if bindings.target_profile_digest != target_profile.content_digest or bindings.target_cht_version != target_profile.cht_core_version:
        raise CHTProductionError(
            [_diagnostic(DiagnosticCode.CHT_RUNTIME_BINDING_INVALID, "Runtime bindings target a different CHT profile.")]
        )
    type_map = {"bool": "string", "string": "string", "enum": "string", "int": "int", "decimal": "decimal", "date": "date", "datetime": "dateTime"}
    for binding in bindings.bindings:
        variable = document.variables.get(binding.variable_id)
        if variable is None:
            raise CHTProductionError(
                [_diagnostic(DiagnosticCode.CHT_RUNTIME_BINDING_INVALID, f"Runtime binding references unknown variable '{binding.variable_id}'.")]
            )
        expected = (
            "date"
            if variable.unit == "calendar_date"
            else "dateTime"
            if variable.unit == "timestamp"
            else type_map.get(variable.type)
        )
        if expected != binding.bind_type:
            raise CHTProductionError(
                [_diagnostic(DiagnosticCode.CHT_RUNTIME_BINDING_INVALID, f"Runtime binding type for '{binding.variable_id}' must be '{expected}'.")]
            )
        _replace_row(
            plan,
            binding.variable_id,
            calculation=binding.calculation,
            bind_type=binding.bind_type,
            role=binding.role,
        )


def _safe_suffix(action_id: str) -> str:
    suffix = action_id.removeprefix("a_").replace("-", "_").replace(".", "_")
    if _SAFE_ROW.fullmatch(suffix) is None:
        raise CHTProductionError(
            [_diagnostic(DiagnosticCode.CAPABILITY_INVOCATION_INVALID, f"Action id '{action_id}' cannot form safe CHT row names.")]
        )
    return suffix


def _bind_type(value_type: str) -> str:
    return {
        "boolean": "string",
        "string": "string",
        "choice": "string",
        "integer": "int",
        "decimal": "decimal",
        "date": "date",
        "datetime": "dateTime",
    }[value_type]


def _cast(expression: str, value_type: str) -> str:
    return f"number({expression})" if value_type in {"integer", "decimal"} else expression


def _lower_capability_action(plan: Any, document: ClinicalIRDocument, capability: Capability) -> GeneratedCHTFile:
    action = next(
        item
        for item in document.actions.values()
        if item.kind == "invoke_capability" and item.capability_id == capability.id
    )
    binding = capability.implementation_binding
    key = (binding.python_module, binding.python_symbol, binding.cht_extension_module)
    lowerer = _REVIEWED_LOWERERS.get(key)
    if lowerer is None:
        raise CHTProductionError(
            [_diagnostic(DiagnosticCode.CHT_CAPABILITY_LOWERER_UNBOUND, "The active capability has no reviewed Python/CHT lowerer.", f"actions.{action.id}")]
        )
    suffix = _safe_suffix(action.id)
    prefix = f"cap_{suffix}"
    module = binding.cht_extension_module
    argument_values = ", ".join(f"${{{action.arguments[item.name]}}}" for item in capability.inputs)
    rows = [
        SurveyRow(type="begin group", name=prefix, appearance="hidden", role="capability_group"),
        SurveyRow(type="calculate", name=f"{prefix}_versions", calculation=f"cht:extension-lib('{module}', 'versions')", role="capability_internal"),
        SurveyRow(type="calculate", name=f"{prefix}_version_match", calculation=f"${{{prefix}_versions}} = '{lowerer.function_version}|{lowerer.reference_version}'", role="capability_internal"),
        SurveyRow(type="calculate", name=f"{prefix}_raw", calculation=f"cht:extension-lib('{module}', 'compute', {argument_values})", role="capability_internal"),
        SurveyRow(type="calculate", name=f"{prefix}_guarded", calculation=f"if(${{{prefix}_version_match}}, ${{{prefix}_raw}}, 'version_mismatch|')", role="capability_internal"),
        SurveyRow(type="calculate", name=f"{prefix}_status", calculation=f"substring-before(${{{prefix}_guarded}}, '|')", role="capability_status"),
        SurveyRow(type="calculate", name=f"{prefix}_payload", calculation=f"substring-after(${{{prefix}_guarded}}, '|')", role="capability_internal"),
    ]
    source_name = f"{prefix}_payload"
    output_rows: dict[str, str] = {}
    for index, output in enumerate(capability.outputs):
        row_name = f"{prefix}_output_{index:02d}"
        is_last = index == len(capability.outputs) - 1
        value_expression = f"${{{source_name}}}" if is_last else f"substring-before(${{{source_name}}}, ',')"
        rows.append(
            SurveyRow(
                type="calculate",
                name=row_name,
                calculation=f"if(${{{prefix}_status}} = 'ok', {_cast(value_expression, output.type)}, '')",
                role="capability_output",
                bind_type=_bind_type(output.type),
            )
        )
        output_rows[output.name] = row_name
        if not is_last:
            remainder = f"{prefix}_remainder_{index:02d}"
            rows.append(
                SurveyRow(type="calculate", name=remainder, calculation=f"substring-after(${{{source_name}}}, ',')", role="capability_internal")
            )
            source_name = remainder
    rows.append(SurveyRow(type="end group", name=prefix, role="capability_group"))
    plan.cht_xlsform.workbook.survey.extend(rows)
    for row in rows:
        plan.cht_xlsform.row_sources[row.name] = [
            {"source_id": capability.id, "note": "registry-selected reviewed capability lowerer"}
        ]
    _replace_row(
        plan,
        action.status_target_var or "",
        calculation=f"${{{prefix}_status}}",
        bind_type="string",
        role="capability_status_alias",
    )
    output_by_name = {item.name: item for item in capability.outputs}
    for mapping in action.mappings:
        output = output_by_name[mapping.record_key]
        _replace_row(
            plan,
            mapping.target_var,
            calculation=f"${{{output_rows[mapping.record_key]}}}",
            bind_type=_bind_type(output.type),
            role="capability_output_alias",
        )
    return GeneratedCHTFile(
        path=f"extension-libs/{module}",
        content=lowerer.source,
        sha256=sha256_text(lowerer.source),
    )


def lower_registered_capabilities(
    plan: Any,
    document: ClinicalIRDocument,
    capabilities: tuple[Capability, ...],
    target_profile: TargetProfile,
) -> None:
    files_by_path: dict[str, GeneratedCHTFile] = {}
    for capability in capabilities:
        file = _lower_capability_action(plan, document, capability)
        prior = files_by_path.get(file.path)
        if prior is not None and prior.sha256 != file.sha256:
            raise CHTProductionError(
                [_diagnostic(DiagnosticCode.IMPLEMENTATION_DIGEST_MISMATCH, f"Reviewed lowerers disagree for '{file.path}'.")]
            )
        files_by_path[file.path] = file
    if files_by_path:
        plan.special_function_bundle = CHTSpecialFunctionBundle(
            profile=reviewed_cht_profile(target_profile.cht_core_version),
            files=tuple(files_by_path[path] for path in sorted(files_by_path)),
            diagnostics=(),
        )


def _validate_resolution_inputs(
    document: ClinicalIRDocument,
    lock: dict[str, Any],
    registry: RegistrySetV2,
    activated: ActivatedRegistryRelease,
    target: TargetProfile,
) -> dict[str, Capability]:
    allowed_root = {"schema_version", "content_digest", "registry_set_digest", "release_digest", "target_profile_digest", "resolution_rule_version", "resolutions"}
    allowed_entry = {
        "need_id",
        "capability_id",
        "capability_version",
        "capability_content_digest",
        "registry_set_digest",
        "target_profile_digest",
        "release_digest",
        "resolution_rule_version",
        "rationale",
    }
    expected_rationale = {
        "rule": "exact_equality_only",
        "matched_fields": list(RESOLUTION_MATCHED_FIELDS),
        "forbidden_selectors": list(RESOLUTION_FORBIDDEN_SELECTORS),
    }
    if (
        not isinstance(lock, dict)
        or set(lock) != allowed_root
        or lock.get("schema_version") != RESOLUTION_LOCK_SCHEMA_VERSION
        or lock.get("resolution_rule_version") != RESOLUTION_RULE_VERSION
        or lock.get("content_digest") != content_digest(lock)
    ):
        raise CHTProductionError(
            [_diagnostic(DiagnosticCode.REGISTRY_RELEASE_MISMATCH, "Resolution lock is malformed or its digest does not match.", "$.resolution_lock")]
        )
    if (
        activated.registry_set_digest != registry.content_digest
        or lock["registry_set_digest"] != registry.content_digest
        or lock["release_digest"] != activated.release_digest
        or target.content_digest != registry.target_profile.content_digest
        or lock["target_profile_digest"] != target.content_digest
    ):
        raise CHTProductionError(
            [_diagnostic(DiagnosticCode.REGISTRY_RELEASE_MISMATCH, "Registry release, resolution lock, and target profile must match exactly.")]
        )
    capabilities = {item.id: item for item in registry.capability_registry.capabilities}
    resolutions = lock.get("resolutions")
    if not isinstance(resolutions, list):
        raise CHTProductionError(
            [_diagnostic(DiagnosticCode.REGISTRY_RELEASE_MISMATCH, "Resolution lock must contain a resolution list.")]
        )
    entries_are_valid = all(
        isinstance(item, dict)
        and set(item) == allowed_entry
        and item.get("resolution_rule_version") == RESOLUTION_RULE_VERSION
        and item.get("rationale") == expected_rationale
        for item in resolutions
    )
    capability_ids = [item.get("capability_id") for item in resolutions if isinstance(item, dict)]
    need_ids = [item.get("need_id") for item in resolutions if isinstance(item, dict)]
    if (
        not entries_are_valid
        or len(capability_ids) != len(set(capability_ids))
        or len(need_ids) != len(set(need_ids))
    ):
        raise CHTProductionError(
            [_diagnostic(DiagnosticCode.REGISTRY_RELEASE_MISMATCH, "Resolution lock entries are malformed or duplicated.", "$.resolution_lock.resolutions")]
        )
    by_id = {item["capability_id"]: item for item in resolutions}
    invoked = {
        action.capability_id
        for action in document.actions.values()
        if action.kind == "invoke_capability"
    }
    if None in invoked or set(by_id) != invoked:
        raise CHTProductionError(
            [_diagnostic(DiagnosticCode.REGISTRY_RELEASE_MISMATCH, "Resolution lock entries must exactly match invoked capabilities.")]
        )
    for capability_id in sorted(invoked):
        capability = capabilities.get(capability_id or "")
        resolution = by_id.get(capability_id)
        if (
            capability is None
            or resolution.get("capability_version") != capability.version
            or resolution.get("capability_content_digest") != capability.content_digest
            or resolution.get("registry_set_digest") != registry.content_digest
            or resolution.get("release_digest") != activated.release_digest
            or resolution.get("target_profile_digest") != target.content_digest
        ):
            raise CHTProductionError(
                [_diagnostic(DiagnosticCode.REGISTRY_RELEASE_MISMATCH, f"Resolution for '{capability_id}' is stale or mismatched.")]
            )
    return capabilities


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def inspect_production_dependencies() -> dict[str, Any]:
    modules = (
        "chw_navigator.cht_production",
        "chw_navigator.cht_backend",
        "chw_navigator.cht_evidence",
        "chw_navigator.cht_local_data",
        "chw_navigator.cht_special_functions",
        "chw_navigator.cht_task_composer",
        "chw_navigator.cht_tasks",
        "chw_navigator.queued_topology",
    )
    forbidden = ("subprocess", "node", "typescript_oracle_runner")
    findings: list[str] = []
    root = Path(__file__).resolve().parent
    for name in modules:
        source = (root / f"{name.rsplit('.', 1)[-1]}.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports: list[str] = []
        for item in ast.walk(tree):
            if isinstance(item, ast.Import):
                imports.extend(alias.name for alias in item.names)
            elif isinstance(item, ast.ImportFrom) and item.module:
                imports.append(item.module)
        findings.extend(
            f"{name}:{import_name}"
            for import_name in imports
            if any(token in import_name.lower() for token in forbidden)
        )
    return {
        "status": "pass" if not findings else "fail",
        "node_required": False if not findings else None,
        "inspected_modules": list(modules),
        "forbidden_dependency_findings": findings,
    }


def build_cht_production_bundle(
    *,
    canonical_ir_path: str | Path,
    resolution_lock_path: str | Path,
    registry_set_path: str | Path,
    activated_release_path: str | Path,
    target_profile_path: str | Path,
    task_bindings_path: str | Path,
    local_data_bindings_path: str | Path,
    runtime_bindings_path: str | Path,
    existing_tasks_path: str | Path,
    output_dir: str | Path,
) -> CHTProductionBuild:
    target_dir = Path(output_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        document = ClinicalIRDocument.from_dict(_load_json(canonical_ir_path))
    except ValueError as exc:
        raise CHTProductionError(
            [_diagnostic(DiagnosticCode.PRODUCT_CONTRACT_INVALID, str(exc), "$.canonical_ir")]
        ) from exc
    errors = validate_document(document)
    if errors:
        raise CHTProductionError(
            [_diagnostic(DiagnosticCode.PRODUCT_CONTRACT_INVALID, item.message, item.path) for item in errors]
        )
    registry = load_registry_set_v2(registry_set_path)
    try:
        activated = ActivatedRegistryRelease.model_validate(_load_json(activated_release_path))
        target_profile = TargetProfile.model_validate(_load_json(target_profile_path))
    except ValidationError as exc:
        raise CHTProductionError(
            [_diagnostic(DiagnosticCode.REGISTRY_RELEASE_MISMATCH, str(exc), "$.release")]
        ) from exc
    lock = _load_json(resolution_lock_path)
    capabilities_by_id = _validate_resolution_inputs(document, lock, registry, activated, target_profile)
    referenced = validate_capability_invocations(document, capabilities_by_id)
    tasks: CHTTaskBindingRegistry = load_cht_task_bindings(task_bindings_path)
    local: CHTLocalDataRegistry = load_cht_local_data_registry(local_data_bindings_path)
    runtime = load_runtime_bindings(runtime_bindings_path)
    if tasks.target_cht_version != target_profile.cht_core_version or local.target_cht_version != target_profile.cht_core_version:
        raise CHTProductionError(
            [_diagnostic(DiagnosticCode.TARGET_PROFILE_UNSUPPORTED, "CHT task/local-data bindings target a different CHT version.")]
        )
    plan = build_cht_lowering_plan(
        document,
        task_bindings=tasks,
        local_data_registry=local,
        form_context="contact",
    )
    apply_runtime_bindings(plan, document, runtime, target_profile)
    lower_registered_capabilities(plan, document, referenced, target_profile)
    plan.target_cht_version = target_profile.cht_core_version
    adapter_dir = target_dir / "generated"
    adapter = write_cht_adapter_bundle(plan, adapter_dir)
    if adapter.tasks_js_path is None:
        raise CHTProductionError(
            [_diagnostic(DiagnosticCode.CHT_TASK_BINDING_INVALID, "The production slice must emit tasks.js.")]
        )
    existing_path = Path(existing_tasks_path)
    existing_bytes = existing_path.read_bytes()
    try:
        existing_text = existing_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CHTProductionError(
            [_diagnostic(DiagnosticCode.CHT_COMPOSITION_INVALID, "Existing tasks.js must be UTF-8.")]
        ) from exc
    generated_text = adapter.tasks_js_path.read_text(encoding="utf-8")
    try:
        composition = compose_tasks_js(existing_text, generated_text)
    except CHTTaskCompositionError as exc:
        raise CHTProductionError(list(exc.diagnostics)) from exc
    composed_path = target_dir / "tasks.js"
    composed_path.write_text(composition.content, encoding="utf-8", newline="\n")
    rollback_dir = target_dir / "rollback"
    rollback_dir.mkdir(exist_ok=True)
    rollback_path = rollback_dir / "tasks.js"
    rollback_path.write_bytes(existing_bytes)
    (target_dir / "task-composition.json").write_text(
        json.dumps(
            {"evidence": composition.evidence, "state": composition.state},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    contracts_dir = target_dir / "contracts"
    contracts_dir.mkdir(exist_ok=True)
    (contracts_dir / "topology-snapshot.schema.json").write_text(
        json.dumps(TopologySnapshot.model_json_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (contracts_dir / "queued-operation.schema.json").write_text(
        json.dumps(QueuedOperation.model_json_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    artifacts = {
        path.relative_to(target_dir).as_posix(): _sha256_bytes(path.read_bytes())
        for path in sorted(target_dir.rglob("*"))
        if path.is_file() and path.name != "evidence-manifest.json"
    }
    dependency_check = inspect_production_dependencies()
    deterministic = {
        "registry_set_digest": registry.content_digest,
        "release_digest": activated.release_digest,
        "resolution_lock_digest": lock["content_digest"],
        "target_profile_digest": target_profile.content_digest,
        "referenced_capabilities": [item.id for item in referenced],
        "emitted_extensions": [path.name for path in adapter.special_function_paths if path.suffix == ".js"],
        "composition": composition.evidence,
        "rollback_exact": rollback_path.read_bytes() == existing_bytes,
        "production_dependency_check": dependency_check,
        "artifacts": artifacts,
    }
    records = [item.to_dict() for item in default_runner_records()]
    evidence = {
        "schema_version": "cht-production-evidence@1.0.0",
        "evidence_level": "E2",
        "deployment_ready": False,
        "deterministic": deterministic,
        "environment_checks": records,
        "evidence_ceiling_reason": "Official harness and exact-target runtime checks were not run by this deterministic build.",
    }
    evidence_path = target_dir / "evidence-manifest.json"
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return CHTProductionBuild(
        output_dir=target_dir,
        adapter=adapter,
        composed_tasks_path=composed_path,
        rollback_tasks_path=rollback_path,
        evidence_manifest_path=evidence_path,
        deterministic=deterministic,
    )
