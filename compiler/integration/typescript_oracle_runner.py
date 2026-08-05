from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any


COMPILER_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = COMPILER_ROOT.parent
SOURCE_LOCK = COMPILER_ROOT / "integration" / "prompt12-source-lock.json"


class TypeScriptOracleUnavailable(RuntimeError):
    pass


def _node() -> str:
    executable = shutil.which("node")
    if executable is None:
        raise TypeScriptOracleUnavailable("Node.js is unavailable")
    return executable


def source_root() -> Path:
    lock = json.loads(SOURCE_LOCK.read_text(encoding="utf-8"))
    root = (REPOSITORY_ROOT / lock["source"]["workspace_relative_path"]).resolve()
    verifier_path = COMPILER_ROOT / "scripts" / "verify_prompt12_source_lock.py"
    spec = importlib.util.spec_from_file_location("ws2_prompt12_source_lock", verifier_path)
    if spec is None or spec.loader is None:
        raise TypeScriptOracleUnavailable("Reviewed TypeScript source-lock verifier cannot be loaded")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    findings = verifier.verify(SOURCE_LOCK, root)
    if findings:
        raise TypeScriptOracleUnavailable(
            "Reviewed TypeScript source lock failed: " + "; ".join(findings)
        )
    return root


def compose_tasks_js(existing_source: str, generated_source: str) -> dict[str, Any]:
    module = source_root() / "packages" / "cht-integration" / "dist" / "index.js"
    if not module.is_file():
        raise TypeScriptOracleUnavailable(f"Reviewed task composer is absent: {module}")
    script = r"""
import { pathToFileURL } from 'node:url';
let raw = '';
for await (const chunk of process.stdin) raw += chunk;
const input = JSON.parse(raw);
const integration = await import(pathToFileURL(process.argv[1]).href);
const first = integration.composeTasksJs(input.existing, input.generated, 'tasks.js');
const state = first.content && first.evidence ? {
  schemaVersion: '1.0.0', projectId: 'ws2-tracer', baseCommit: 'fixture', integrationBranch: 'fixture',
  targetProfile: { chtVersion: '5.2.0', chtConfVersion: '6.4.1' }, bundleHash: 'sha256:fixture',
  workflow: 'ws2-tracer', managedFiles: {},
  taskComposition: {
    file: 'tasks.js', composedFileSha256: integration.sha256Text(first.content),
    blockSha256: first.evidence.blockSha256, generatedTasksSha256: first.evidence.generatedTasksSha256,
    variableName: first.evidence.variableName,
    ruleNames: first.evidence.ruleIdentities.map(item => item.name),
    eventIds: first.evidence.ruleIdentities.flatMap(item => item.eventIds)
  }
} : undefined;
const second = integration.composeTasksJs(first.content, input.generated, 'tasks.js', state);
console.log(JSON.stringify({
  content: first.content,
  evidence: first.evidence,
  diagnostics: first.diagnostics,
  idempotent: second.content === first.content,
  secondDiagnostics: second.diagnostics
}));
"""
    completed = subprocess.run(
        [_node(), "--input-type=module", "-e", script, str(module)],
        input=json.dumps({"existing": existing_source, "generated": generated_source}),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    result = json.loads(completed.stdout)
    errors = [item for item in result["diagnostics"] if item.get("severity") == "error"]
    second_errors = [
        item for item in result["secondDiagnostics"] if item.get("severity") == "error"
    ]
    if errors or second_errors or not result["idempotent"]:
        raise RuntimeError(
            "TypeScript task composition failed closed: "
            f"{errors or second_errors or 'non-idempotent'}"
        )
    return result


def run_legacy_gestational_age(input_value: dict[str, str]) -> dict[str, Any]:
    module = source_root() / "packages" / "special-functions" / "dist" / "index.js"
    if not module.is_file():
        raise TypeScriptOracleUnavailable(f"Reviewed special-function oracle is absent: {module}")
    script = r"""
import { pathToFileURL } from 'node:url';
let raw = '';
for await (const chunk of process.stdin) raw += chunk;
const input = JSON.parse(raw);
const api = await import(pathToFileURL(process.argv[1]).href);
const result = api.calculateGestationalAgeFromLmp({
  lmpDate: input.lmp_date,
  asOfDate: input.reference_date,
  functionVersion: '1.0.0',
  referenceDataVersion: 'calendar-280-day-v1'
});
console.log(JSON.stringify(result));
"""
    completed = subprocess.run(
        [_node(), "--input-type=module", "-e", script, str(module)],
        input=json.dumps(input_value),
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    return json.loads(completed.stdout)


def compare_naegele_overlap(vectors: list[dict[str, Any]], python_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    comparable = [item for item in vectors if item["status"] == "ok"]
    cases: list[dict[str, Any]] = []
    for vector in comparable:
        typescript = run_legacy_gestational_age(vector["input"])
        python = python_results[vector["name"]]
        technical = python["technical"]
        expected_decimal = round(technical["ga_weeks"] + technical["ga_days_remainder"] / 7, 1)
        passed = (
            typescript["status"] == python["status"]
            and typescript["technical"]["estimatedDeliveryDate"] == technical["edd"]
            and typescript["technical"]["gestationalAgeWeeks"] == expected_decimal
        )
        cases.append({"case_id": f"tracer.{vector['name']}", "status": "pass" if passed else "fail"})
    return {
        "comparable_count": len(cases),
        "not_comparable_count": len(vectors) - len(cases),
        "cases": cases,
        "status": "pass" if cases and all(item["status"] == "pass" for item in cases) else "fail",
    }
