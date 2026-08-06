from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any

from .cht_backend import CHTAdapterArtifacts, build_cht_lowering_plan, write_cht_adapter_bundle
from .cht_local_data import load_cht_local_data_registry
from .cht_special_functions import (
    CHTSpecialFunctionBundle,
    GeneratedCHTFile,
    naegele_extension_source,
    reviewed_cht_profile,
)
from .cht_tasks import load_cht_task_bindings
from .clinical_ir import ClinicalIRDocument
from .diagnostics import Diagnostic, DiagnosticCode
from .form_ir import SurveyRow
from .registry_set import Capability, RegistrySetError, load_registry_set, resolve_capability
from .special_functions import (
    NAEGELE_FUNCTION_VERSION,
    NAEGELE_REFERENCE_VERSION,
    SPECIAL_FUNCTION_STATUSES,
    calculate_gestational_age_naegele,
    sha256_text,
)
from .validator import validate_document


COMPILER_ROOT = Path(__file__).resolve().parents[2]
TRACER_EXAMPLES = COMPILER_ROOT / "examples" / "tracer"


@dataclass(frozen=True, slots=True)
class TracerBuild:
    output_dir: Path
    evidence_manifest: Path
    adapter: CHTAdapterArtifacts
    deterministic: dict[str, Any]
    environment: dict[str, Any]


class TracerBuildError(ValueError):
    def __init__(self, diagnostics: list[Diagnostic] | tuple[Diagnostic, ...]):
        self.diagnostics = tuple(diagnostics)
        super().__init__("Tracer build failed closed:\n" + "\n".join(f"{d.code}: {d.message}" for d in diagnostics))


def _diagnostic(code: DiagnosticCode, message: str, path: str | None = None) -> Diagnostic:
    return Diagnostic(code=code, severity="error", message=message, path=path)


def _load_document(path: Path) -> ClinicalIRDocument:
    document = ClinicalIRDocument.from_dict(json.loads(path.read_text(encoding="utf-8")))
    errors = validate_document(document)
    if errors:
        raise TracerBuildError(
            [_diagnostic(DiagnosticCode.CAPABILITY_INVOCATION_INVALID, item.message, item.path) for item in errors]
        )
    return document


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


def validate_capability_invocation(document: ClinicalIRDocument, capability: Capability) -> None:
    actions = [item for item in document.actions.values() if item.kind == "invoke_capability"]
    diagnostics: list[Diagnostic] = []
    if len(actions) != 1:
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.CAPABILITY_INVOCATION_INVALID,
                "The narrow tracer requires exactly one invoke_capability action.",
                "actions",
            )
        )
    for action in actions:
        expected_inputs = [item.name for item in capability.inputs]
        if list(action.arguments) != expected_inputs:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CAPABILITY_INVOCATION_INVALID,
                    f"Capability arguments must preserve registered order: {', '.join(expected_inputs)}.",
                    f"actions.{action.id}.arguments",
                )
            )
        expected_outputs = [item.name for item in capability.outputs]
        actual_outputs = [item.record_key for item in action.mappings]
        if actual_outputs != expected_outputs:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CAPABILITY_INVOCATION_INVALID,
                    f"Capability output mappings must preserve registered order: {', '.join(expected_outputs)}.",
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
                    f"Capability caller is missing explicit status branches: {', '.join(missing)}.",
                    "decisions",
                )
            )
    if diagnostics:
        raise TracerBuildError(diagnostics)


def _replace_row(plan, name: str, *, calculation: str, role: str, bind_type: str = "") -> None:
    row = next((item for item in plan.cht_xlsform.workbook.survey if item.name == name), None)
    if row is None:
        raise TracerBuildError(
            [_diagnostic(DiagnosticCode.CAPABILITY_INVOCATION_INVALID, f"Generated form row '{name}' is absent.")]
        )
    row.type = "calculate"
    row.label = ""
    row.required = ""
    row.calculation = calculation
    row.role = role
    row.bind_type = bind_type


def _inject_capability_rows(plan, document: ClinicalIRDocument, capability: Capability) -> None:
    action = next(item for item in document.actions.values() if item.kind == "invoke_capability")
    module = capability.implementation_binding.cht_extension_module
    technical_rows = [
        SurveyRow(type="begin group", name="technical", appearance="hidden", role="capability_group"),
        SurveyRow(
            type="calculate",
            name="ga_versions",
            calculation=f"cht:extension-lib('{module}', 'versions')",
            role="capability_internal",
        ),
        SurveyRow(
            type="calculate",
            name="ga_version_match",
            calculation=f"${{ga_versions}} = '{NAEGELE_FUNCTION_VERSION}|{NAEGELE_REFERENCE_VERSION}'",
            role="capability_internal",
        ),
        SurveyRow(
            type="calculate",
            name="ga_raw",
            calculation=(
                f"cht:extension-lib('{module}', 'compute', "
                f"${{{action.arguments['lmp_date']}}}, ${{{action.arguments['reference_date']}}})"
            ),
            role="capability_internal",
        ),
        SurveyRow(
            type="calculate",
            name="ga_guarded",
            calculation="if(${ga_version_match}, ${ga_raw}, 'version_mismatch|')",
            role="capability_internal",
        ),
        SurveyRow(type="calculate", name="ga_status", calculation="substring-before(${ga_guarded}, '|')", role="capability_status"),
        SurveyRow(type="calculate", name="ga_payload", calculation="substring-after(${ga_guarded}, '|')", role="capability_internal"),
        SurveyRow(type="calculate", name="ga_after_weeks", calculation="substring-after(${ga_payload}, ',')", role="capability_internal"),
        SurveyRow(type="calculate", name="ga_weeks", calculation="if(${ga_status} = 'ok', number(substring-before(${ga_payload}, ',')), '')", role="capability_output", bind_type="int"),
        SurveyRow(type="calculate", name="ga_days_remainder", calculation="if(${ga_status} = 'ok', number(substring-before(${ga_after_weeks}, ',')), '')", role="capability_output", bind_type="int"),
        SurveyRow(type="calculate", name="edd", calculation="if(${ga_status} = 'ok', substring-after(${ga_after_weeks}, ','), '')", role="capability_output", bind_type="date"),
        SurveyRow(type="end group", name="technical", role="capability_group"),
    ]
    plan.cht_xlsform.workbook.survey.extend(technical_rows)
    for row in technical_rows:
        plan.cht_xlsform.row_sources[row.name] = [{"source_id": "TRACER_POLICY", "note": "registry-resolved technical binding"}]
    _replace_row(plan, "st_reference_date", calculation="today()", role="capability_input")
    _replace_row(
        plan,
        "st_lmp_availability",
        calculation="${local_status__st_lmp_date_h}",
        role="local_data_status_alias",
    )
    _replace_row(plan, action.status_target_var or "", calculation="${ga_status}", role="capability_status_alias")
    output_bindings = {item.name: item.binding_path.split(".", 1)[1] for item in capability.outputs}
    for mapping in action.mappings:
        _replace_row(
            plan,
            mapping.target_var,
            calculation=f"${{{output_bindings[mapping.record_key]}}}",
            role="capability_output_alias",
            bind_type={"ga_weeks": "int", "ga_days_remainder": "int", "edd": "date"}[mapping.record_key],
        )


def _capability_bundle(capability: Capability, target_cht_version: str) -> CHTSpecialFunctionBundle:
    source = naegele_extension_source()
    module_path = f"extension-libs/{capability.implementation_binding.cht_extension_module}"
    return CHTSpecialFunctionBundle(
        profile=reviewed_cht_profile(target_cht_version),
        files=(GeneratedCHTFile(path=module_path, content=source, sha256=sha256_text(source)),),
        diagnostics=(),
    )


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _python_vector_results(vectors: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for vector in vectors:
        result = calculate_gestational_age_naegele(**vector["input"]).to_dict()
        if result["status"] != vector["status"] or result.get("technical") != vector.get("technical"):
            raise TracerBuildError(
                [_diagnostic(DiagnosticCode.CAPABILITY_INVOCATION_INVALID, f"Reference vector failed: {vector['name']}")]
            )
        results[vector["name"]] = result
    return results


def _run_node_harness(module_path: Path, xform_path: Path) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        return {"status": "not_run", "reason": "Node.js is unavailable"}
    script = r"""
const fs = require('node:fs');
const fn = require(process.argv[1]);
const xform = fs.readFileSync(process.argv[2], 'utf8');
const requiredFormFragments = [
  "cht:extension-lib('gestational-age-from-lmp.js', 'compute'",
  'nodeset="/data/technical/ga_weeks" type="int"',
  'nodeset="/data/technical/ga_days_remainder" type="int"',
  'nodeset="/data/technical/edd" type="date"'
];
if (!requiredFormFragments.every(fragment => xform.includes(fragment))) process.exit(3);
const env = value => ({ t: 'str', v: value });
const result = fn(env('compute'), env('2026-01-01'), env('2026-01-09'));
if (result.t !== 'str' || result.v !== 'ok|1,1,2026-10-08') process.exit(2);
"""
    completed = subprocess.run(
        [node, "-e", script, str(module_path), str(xform_path)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    return {
        "status": "pass" if completed.returncode == 0 else "fail",
        **({"reason": completed.stderr or completed.stdout} if completed.returncode else {}),
    }


def build_tracer(
    output_dir: str | Path,
    *,
    evidence_manifest: str | Path | None = None,
    examples_dir: str | Path = TRACER_EXAMPLES,
) -> TracerBuild:
    oracle_path = COMPILER_ROOT / "integration" / "typescript_oracle_runner.py"
    spec = importlib.util.spec_from_file_location("chw_navigator_typescript_oracle_runner", oracle_path)
    if spec is None or spec.loader is None:
        raise TracerBuildError(
            [_diagnostic(DiagnosticCode.CAPABILITY_INVOCATION_INVALID, "Could not load TypeScript oracle runner.")]
        )
    oracle_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle_module)

    examples = Path(examples_dir)
    target = Path(output_dir).resolve()
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    document = _load_document(examples / "tracer.ir.json")
    registry = load_registry_set(examples / "registry-set.json")
    invocation = next(item for item in document.actions.values() if item.kind == "invoke_capability")
    try:
        capability = resolve_capability(
            registry,
            invocation.capability_id or "",
            required_target_features=("registered_local_read", "recorded_at_freshness", "extension_lib_xpath"),
        )
    except RegistrySetError as exc:
        raise TracerBuildError(list(exc.diagnostics)) from exc
    validate_capability_invocation(document, capability)
    local_registry = load_cht_local_data_registry(examples / "local-data-bindings.json")
    task_registry = load_cht_task_bindings(examples / "task-bindings.json")
    if registry.target_profile.cht_core_version != task_registry.target_cht_version:
        raise TracerBuildError(
            [_diagnostic(DiagnosticCode.TARGET_PROFILE_UNSUPPORTED, "Tracer target and task bindings disagree.")]
        )
    plan = build_cht_lowering_plan(
        document,
        task_bindings=task_registry,
        local_data_registry=local_registry,
        form_context="contact",
    )
    _inject_capability_rows(plan, document, capability)
    plan.special_function_bundle = _capability_bundle(capability, registry.target_profile.cht_core_version)
    plan.target_cht_version = registry.target_profile.cht_core_version
    adapter = write_cht_adapter_bundle(plan, target)

    existing = (examples / "existing-tasks.js").read_text(encoding="utf-8")
    rollback_dir = target / "rollback"
    rollback_dir.mkdir()
    rollback_path = rollback_dir / "tasks.js"
    rollback_path.write_bytes((examples / "existing-tasks.js").read_bytes())
    try:
        composition = oracle_module.compose_tasks_js(existing, adapter.tasks_js_path.read_text(encoding="utf-8"))
    except oracle_module.TypeScriptOracleUnavailable as exc:
        raise TracerBuildError([_diagnostic(DiagnosticCode.CAPABILITY_INVOCATION_INVALID, str(exc))]) from exc
    composed_path = target / "composed-tasks.js"
    composed_path.write_text(composition["content"], encoding="utf-8", newline="\n")
    composition_path = target / "task-composition.json"
    composition_path.write_text(
        json.dumps(
            {
                "schema_version": "tracer-task-composition@1.0.0",
                "idempotent": composition["idempotent"],
                "existing_sha256": _sha256(examples / "existing-tasks.js"),
                "rollback_sha256": _sha256(rollback_path),
                "composed_sha256": _sha256(composed_path),
                "evidence": composition["evidence"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    vectors_payload = json.loads((examples / "reference-vectors.json").read_text(encoding="utf-8"))
    vector_results = _python_vector_results(vectors_payload["vectors"])
    oracle = oracle_module.compare_naegele_overlap(vectors_payload["vectors"], vector_results)
    harness = _run_node_harness(
        target / "extension-libs" / capability.implementation_binding.cht_extension_module,
        adapter.form_xform_path,
    )

    artifact_paths = sorted(
        path for path in target.rglob("*") if path.is_file() and path.name != "tracer-evidence-manifest.json"
    )
    deterministic = {
        "registry_set_digest": registry.content_digest,
        "capability_id": capability.id,
        "capability_version": capability.version,
        "artifacts": {path.relative_to(target).as_posix(): _sha256(path) for path in artifact_paths},
        "task_composition": {"idempotent": composition["idempotent"], "rollback_exact": rollback_path.read_bytes() == (examples / "existing-tasks.js").read_bytes()},
        "oracle": oracle,
        "harness": harness,
    }
    environment = {
        "python": sys.version.split()[0],
        "node": shutil.which("node"),
        "platform": platform.platform(),
        "exact_cht_sandbox": {"status": "not_run", "reason": "Exact CHT 5.2.0 sandbox is external evidence."},
    }
    level = "E2" if harness["status"] in {"pass", "not_run"} and oracle["status"] == "pass" else "E0"
    manifest_value = {
        "schema_version": "tracer-evidence@1.0.0",
        "deterministic": deterministic,
        "environment": environment,
        "evidence_level": level,
        "deployment_ready": False,
    }
    manifest_path = Path(evidence_manifest) if evidence_manifest is not None else COMPILER_ROOT / "reports" / "tracer-evidence-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest_value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return TracerBuild(target, manifest_path, adapter, deterministic, environment)
