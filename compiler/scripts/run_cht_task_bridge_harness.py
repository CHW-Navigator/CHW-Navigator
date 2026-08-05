"""Run Python-generated tasks.js through the reviewed official CHT harness fixture."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


COMPILER_ROOT = Path(__file__).resolve().parents[1]
SRC = COMPILER_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.cht_backend import build_cht_lowering_plan, write_cht_adapter_bundle
from chw_navigator.cht_tasks import load_cht_task_bindings
from chw_navigator.clinical_ir import ClinicalIRDocument


def _default_reviewed_root() -> Path:
    return (
        COMPILER_ROOT.parents[1]
        / "generated"
        / "prompt12-execution"
        / "chw-prompt12"
    )


def run(reviewed_root: Path, output_root: Path) -> dict[str, object]:
    output_root = output_root.resolve()
    compiler_root = COMPILER_ROOT.resolve()
    if output_root == compiler_root or compiler_root not in output_root.parents:
        raise RuntimeError("Harness output must be a child of the compiler workspace.")
    harness_root = reviewed_root / "integration" / "official-cht-harness"
    source_project = harness_root / "workspace" / "4.22.0" / "schedule_followup"
    runner = harness_root / "run-harness.mjs"
    if not source_project.is_dir() or not runner.is_file():
        raise FileNotFoundError("Reviewed official CHT harness fixture is missing.")

    document = ClinicalIRDocument.from_dict(
        json.loads((COMPILER_ROOT / "examples" / "cht_task_typescript_bridge.ir.json").read_text(encoding="utf-8"))
    )
    bindings = load_cht_task_bindings(
        COMPILER_ROOT / "examples" / "cht-task-bindings.typescript-bridge.json"
    )
    generated_root = output_root / "python-bundle"
    plan = build_cht_lowering_plan(document, task_bindings=bindings)
    artifacts = write_cht_adapter_bundle(plan, generated_root)
    if artifacts.tasks_js_path is None or artifacts.form_survey_path is None:
        raise RuntimeError("Python CHT build did not emit task artifacts.")

    staged_workspace = output_root / "official-workspace"
    staged_project = staged_workspace / "4.22.0" / "schedule_followup"
    if staged_workspace.exists():
        if output_root not in staged_workspace.resolve().parents:
            raise RuntimeError("Refusing to replace a staged workspace outside the requested output root.")
        shutil.rmtree(staged_workspace)
    shutil.copytree(source_project, staged_project)
    shutil.copy2(artifacts.tasks_js_path, staged_project / "tasks.js")

    survey = artifacts.form_survey_path.read_text(encoding="utf-8")
    staged_form = (
        staged_project
        / "forms"
        / "app"
        / "chw_nav_task_intent_schedule_followup_schedule_followup.xml"
    ).read_text(encoding="utf-8")
    required_fields = (
        "required",
        "task_type",
        "due_days",
        "start_days",
        "end_days",
        "followup_form",
        "operation_id",
        "local_write_intent",
        "sync_observation",
        "task_visibility_state",
    )
    missing_contract_fields = [
        name
        for name in required_fields
        if f'"{name}"' not in survey or f"<{name}/>" not in staged_form
    ]
    if missing_contract_fields:
        raise RuntimeError(f"Form/task bridge fields are missing: {', '.join(missing_contract_fields)}")

    environment = dict(os.environ)
    environment["CHW_OFFICIAL_HARNESS_WORKSPACE"] = str(staged_workspace)
    result = subprocess.run(
        ["node", str(runner)],
        cwd=harness_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    report = {
        "schema_version": "cht-task-bridge-harness@1.0.0",
        "status": "pass" if result.returncode == 0 else "fail",
        "python_tasks_js": str(artifacts.tasks_js_path),
        "reviewed_fixture": str(source_project),
        "staged_workspace": str(staged_workspace),
        "field_contract_checked": list(required_fields),
        "official_harness_exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "limit": (
            "The official fixture executes the Python-generated task rules with the reviewed XML form that has the same "
            "task-intent fields. The Python XLSForm CSV still requires conversion and target-project compilation."
        ),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "cht-task-bridge-harness-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"Official CHT harness failed; see {report_path}")
    return {**report, "report_path": str(report_path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviewed-root", type=Path, default=_default_reviewed_root())
    parser.add_argument(
        "--output-root",
        type=Path,
        default=COMPILER_ROOT / "generated" / "cht-task-bridge-harness",
    )
    args = parser.parse_args()
    try:
        report = run(args.reviewed_root.resolve(), args.output_root.resolve())
    except (FileNotFoundError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"CHT task bridge harness failed: {exc}", file=sys.stderr)
        return 1
    print(f"CHT task bridge harness passed: {report['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
