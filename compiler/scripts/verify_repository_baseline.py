"""Run and report the WS0 repository baseline without overstating evidence."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Sequence


COMPILER_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = COMPILER_ROOT.parent
DEFAULT_MANIFEST = COMPILER_ROOT / "reports" / "baseline-manifest.json"
SOURCE_LOCK = COMPILER_ROOT / "integration" / "prompt12-source-lock.json"
OVERLAP_MAP = COMPILER_ROOT / "integration" / "oracle-overlap-map.json"
WORK_LOG = COMPILER_ROOT / "docs" / "work-log.md"

EVID_INVALID_RESULT = "CHWN-EVID-001"
EVID_WORK_LOG_INCOMPLETE = "CHWN-EVID-002"
EVID_OVERLAP_INVALID = "CHWN-EVID-003"
EVID_ARCHIVE_AS_CURRENT = "CHWN-EVID-004"
EVID_DIRTY_SOURCE = "CHWN-EVID-005"
EVID_RELEASE_INCOMPLETE = "CHWN-EVID-006"
EVID_SOURCE_TRUTH_DRIFT = "CHWN-EVID-007"

RESULTS = {"pass", "fail", "skipped", "not_run", "not_supplied", "not_comparable"}


@dataclass(slots=True)
class SuiteResult:
    suite_id: str
    status: str
    pass_count: int = 0
    fail_count: int = 0
    skipped_count: int = 0
    not_run_count: int = 0
    warnings_count: int = 0
    total_count: int = 0
    skip_reasons: list[dict[str, str]] = field(default_factory=list)
    command: list[str] = field(default_factory=list)
    evidence_level: str = "E0"
    returncode: int | None = None
    diagnostics: list[dict[str, str]] = field(default_factory=list)


def _diagnostic(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _integer(pattern: str, text: str) -> int:
    match = re.search(pattern, text, flags=re.MULTILINE)
    return int(match.group(1)) if match else 0


def _suite_status(*, returncode: int, failures: int, skipped: int, not_run: int = 0) -> str:
    if returncode != 0 or failures:
        return "fail"
    if not_run:
        return "not_run"
    if skipped:
        return "skipped"
    return "pass"


def parse_unittest_output(output: str, returncode: int, suite_id: str = "compiler-python") -> SuiteResult:
    total = _integer(r"Ran\s+(\d+)\s+tests?", output)
    failures = _integer(r"failures=(\d+)", output)
    errors = _integer(r"errors=(\d+)", output)
    skipped = _integer(r"skipped=(\d+)", output)
    failed = failures + errors
    reasons = [
        {"test": match.group(1).strip(), "reason": match.group(2).strip()}
        for match in re.finditer(r"^(test.*?)\s+\.\.\.\s+skipped\s+['\"](.+?)['\"]$", output, re.MULTILINE)
    ]
    diagnostics: list[dict[str, str]] = []
    if total == 0:
        diagnostics.append(_diagnostic(EVID_INVALID_RESULT, "unittest output has no executed-test total"))
    if skipped != len(reasons):
        diagnostics.append(
            _diagnostic(EVID_INVALID_RESULT, "unittest skipped count does not match enumerated reasons")
        )
    status = _suite_status(returncode=returncode, failures=failed, skipped=skipped)
    return SuiteResult(
        suite_id=suite_id,
        status=status,
        pass_count=max(0, total - failed - skipped),
        fail_count=failed,
        skipped_count=skipped,
        total_count=total,
        skip_reasons=reasons,
        evidence_level="E1" if status == "pass" else "E0",
        returncode=returncode,
        diagnostics=diagnostics,
    )


def parse_pytest_output(output: str, returncode: int, suite_id: str = "product-python") -> SuiteResult:
    passed = _integer(r"(\d+)\s+passed", output)
    failed = _integer(r"(\d+)\s+failed", output)
    skipped = _integer(r"(\d+)\s+skipped", output)
    warnings = _integer(r"(\d+)\s+warnings?", output)
    reasons = [
        {"test": match.group(1).strip(), "reason": match.group(2).strip()}
        for match in re.finditer(r"^SKIPPED\s+\[[^]]+\]\s+([^:]+(?:::[^:]+)*):\s+(.+)$", output, re.MULTILINE)
    ]
    diagnostics: list[dict[str, str]] = []
    total = passed + failed + skipped
    if total == 0:
        diagnostics.append(_diagnostic(EVID_INVALID_RESULT, "pytest output has no executed-test total"))
    if skipped and not reasons:
        diagnostics.append(_diagnostic(EVID_INVALID_RESULT, "pytest skips have no enumerated reasons"))
    status = _suite_status(returncode=returncode, failures=failed, skipped=skipped)
    return SuiteResult(
        suite_id=suite_id,
        status=status,
        pass_count=passed,
        fail_count=failed,
        skipped_count=skipped,
        warnings_count=warnings,
        total_count=total,
        skip_reasons=reasons,
        evidence_level="E1" if status == "pass" else "E0",
        returncode=returncode,
        diagnostics=diagnostics,
    )


def parse_node_test_output(output: str, returncode: int, suite_id: str = "typescript-oracle") -> SuiteResult:
    tests = sum(int(value) for value in re.findall(r"^# tests (\d+)$", output, re.MULTILINE))
    passed = sum(int(value) for value in re.findall(r"^# pass (\d+)$", output, re.MULTILINE))
    failed = sum(int(value) for value in re.findall(r"^# fail (\d+)$", output, re.MULTILINE))
    skipped = sum(int(value) for value in re.findall(r"^# skipped (\d+)$", output, re.MULTILINE))
    reasons = [
        {"test": match.group(1).strip(), "reason": match.group(2).strip()}
        for match in re.finditer(r"^ok\s+\d+\s+-\s+(.+?)\s+# SKIP\s+(.+)$", output, re.MULTILINE)
    ]
    diagnostics: list[dict[str, str]] = []
    if tests == 0:
        diagnostics.append(_diagnostic(EVID_INVALID_RESULT, "Node test output has no executed-test total"))
    if passed + failed + skipped != tests:
        diagnostics.append(_diagnostic(EVID_INVALID_RESULT, "Node test subtotals do not match total"))
    if skipped != len(reasons):
        diagnostics.append(_diagnostic(EVID_INVALID_RESULT, "Node skips do not all have enumerated reasons"))
    status = _suite_status(returncode=returncode, failures=failed, skipped=skipped)
    return SuiteResult(
        suite_id=suite_id,
        status=status,
        pass_count=passed,
        fail_count=failed,
        skipped_count=skipped,
        total_count=tests,
        skip_reasons=reasons,
        evidence_level="E1" if status == "pass" else "E0",
        returncode=returncode,
        diagnostics=diagnostics,
    )


def _run(command: Sequence[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command), cwd=cwd, check=False, capture_output=True, text=True, timeout=timeout
    )


def run_compiler_suite() -> SuiteResult:
    python = REPOSITORY_ROOT / ".venv" / "Scripts" / "python.exe"
    command = [str(python), "-m", "unittest", "discover", "-s", "tests", "-v"]
    if not python.is_file():
        return SuiteResult(
            suite_id="compiler-python",
            status="not_run",
            not_run_count=1,
            command=command,
            diagnostics=[_diagnostic(EVID_INVALID_RESULT, "repository Python environment is absent")],
        )
    completed = _run(command, cwd=COMPILER_ROOT, timeout=900)
    result = parse_unittest_output(completed.stdout + completed.stderr, completed.returncode)
    result.command = command
    return result


def run_product_suite() -> SuiteResult:
    python = REPOSITORY_ROOT / "Product" / ".e2e-venv" / "Scripts" / "python.exe"
    command = [str(python), "-m", "pytest", "-q", "-ra"]
    if not python.is_file():
        return SuiteResult(
            suite_id="product-python",
            status="not_run",
            not_run_count=1,
            command=command,
            diagnostics=[_diagnostic(EVID_INVALID_RESULT, "Product pytest environment is absent")],
        )
    completed = _run(command, cwd=REPOSITORY_ROOT / "Product" / "backend", timeout=900)
    result = parse_pytest_output(completed.stdout + completed.stderr, completed.returncode)
    result.command = command
    return result


def _configured_oracle_root() -> Path:
    payload = json.loads(SOURCE_LOCK.read_text(encoding="utf-8"))
    return (REPOSITORY_ROOT / payload["source"]["workspace_relative_path"]).resolve()


def robocopy_succeeded(returncode: int) -> bool:
    """Robocopy uses 0-7 for success/warnings and 8+ for failures."""

    return 0 <= returncode <= 7


def copy_oracle_source(source: Path, target: Path) -> None:
    robocopy = shutil.which("robocopy") if os.name == "nt" else None
    if robocopy is not None:
        target.mkdir(parents=True, exist_ok=True)
        completed = _run(
            [robocopy, str(source), str(target), "/E", "/XD", "node_modules"],
            cwd=REPOSITORY_ROOT,
            timeout=300,
        )
        if not robocopy_succeeded(completed.returncode):
            raise OSError(f"robocopy failed with exit code {completed.returncode}")
        return
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("node_modules"))


def run_typescript_suite() -> SuiteResult:
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    source = _configured_oracle_root()
    if npm is None or not (source / "package.json").is_file():
        reason = "npm is absent" if npm is None else "pinned TypeScript source is absent"
        return SuiteResult(
            suite_id="typescript-oracle",
            status="not_run",
            not_run_count=1,
            diagnostics=[_diagnostic(EVID_INVALID_RESULT, reason)],
        )
    with tempfile.TemporaryDirectory(prefix="chw-ts-oracle-ws0-") as raw:
        target = Path(raw) / "oracle"
        try:
            copy_oracle_source(source, target)
        except (OSError, shutil.Error) as error:
            return SuiteResult(
                suite_id="typescript-oracle",
                status="fail",
                fail_count=1,
                total_count=1,
                diagnostics=[
                    _diagnostic(EVID_INVALID_RESULT, f"cannot create disposable oracle copy: {error}")
                ],
            )
        install = _run([npm, "ci"], cwd=target, timeout=600)
        if install.returncode != 0:
            return SuiteResult(
                suite_id="typescript-oracle",
                status="fail",
                fail_count=1,
                total_count=1,
                command=[npm, "ci"],
                returncode=install.returncode,
                diagnostics=[_diagnostic(EVID_INVALID_RESULT, "npm ci failed in disposable oracle copy")],
            )
        command = [npm, "test"]
        completed = _run(command, cwd=target, timeout=1200)
        result = parse_node_test_output(completed.stdout + completed.stderr, completed.returncode)
        result.command = command
        return result


def validate_work_log(path: Path = WORK_LOG, ws: str = "WS0") -> list[dict[str, str]]:
    if not path.is_file():
        return [_diagnostic(EVID_WORK_LOG_INCOMPLETE, f"work log is absent: {path}")]
    text = path.read_text(encoding="utf-8")
    marker = re.search(rf"^##\s+{re.escape(ws)}\b.*$", text, re.MULTILINE)
    if marker is None:
        return [_diagnostic(EVID_WORK_LOG_INCOMPLETE, f"work log has no {ws} entry")]
    section = text[marker.start() :]
    next_heading = re.search(r"^##\s+", section[marker.end() - marker.start() :], re.MULTILINE)
    if next_heading:
        section = section[: marker.end() - marker.start() + next_heading.start()]
    required = (
        "Delivered:",
        "Deviations:",
        "Defects found:",
        "Root cause:",
        "Generalized guardrail:",
        "Status ledger:",
        "Evidence level earned:",
        "Blocked on:",
    )
    missing = [label for label in required if not re.search(rf"\*\*{re.escape(label)}\*\*\s+\S", section)]
    return [
        _diagnostic(EVID_WORK_LOG_INCOMPLETE, f"{ws} work-log field missing or empty: {label}")
        for label in missing
    ]


def validate_overlap_map(path: Path = OVERLAP_MAP) -> list[dict[str, str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [_diagnostic(EVID_OVERLAP_INVALID, f"cannot read overlap map: {error}")]
    cases = payload.get("cases")
    if payload.get("schema") != "oracle-overlap-map@1" or not isinstance(cases, list):
        return [_diagnostic(EVID_OVERLAP_INVALID, "overlap map schema/cases are invalid")]
    diagnostics: list[dict[str, str]] = []
    comparable = [case for case in cases if case.get("comparability") == "comparable"]
    if not comparable:
        diagnostics.append(_diagnostic(EVID_OVERLAP_INVALID, "comparable set is empty"))
    seen: set[str] = set()
    for case in cases:
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            diagnostics.append(_diagnostic(EVID_OVERLAP_INVALID, "case IDs must be non-empty and unique"))
            continue
        seen.add(case_id)
        if case.get("comparability") == "not_comparable":
            reason = case.get("reason")
            if not isinstance(reason, str) or not reason.strip() or "not implemented" in reason.lower():
                diagnostics.append(
                    _diagnostic(EVID_OVERLAP_INVALID, f"{case_id} has no semantic non-comparability reason")
                )
    return diagnostics


def reject_archived_current_evidence(paths: Sequence[str]) -> list[dict[str, str]]:
    return [
        _diagnostic(EVID_ARCHIVE_AS_CURRENT, f"archived Prompt 12 evidence cannot be current: {path}")
        for path in paths
        if "generated/prompt12-" in path.replace("\\", "/")
    ]


def validate_source_truth(
    required: dict[Path, tuple[str, ...]] | None = None,
) -> list[dict[str, str]]:
    required = required or {
        REPOSITORY_ROOT / "README.md": (
            "CHW-Navigator-current is the authoritative repository",
            "Python production compiler",
            "read-only differential oracle",
        ),
        REPOSITORY_ROOT / "STATUS.md": (
            "Python production-compiler source of truth",
            "not deployment approval",
        ),
    }
    diagnostics: list[dict[str, str]] = []
    for path, phrases in required.items():
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        normalized = re.sub(r"\s+", " ", text.replace("`", ""))
        for phrase in phrases:
            if phrase not in normalized:
                diagnostics.append(
                    _diagnostic(EVID_SOURCE_TRUTH_DRIFT, f"{path.name} is missing source-truth phrase: {phrase}")
                )
    return diagnostics


def verify_source_lock() -> list[dict[str, str]]:
    script = COMPILER_ROOT / "scripts" / "verify_prompt12_source_lock.py"
    spec = importlib.util.spec_from_file_location("verify_prompt12_source_lock", script)
    if spec is None or spec.loader is None:
        return [_diagnostic(EVID_SOURCE_TRUTH_DRIFT, "source-lock verifier cannot be loaded")]
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return [
        _diagnostic(EVID_SOURCE_TRUTH_DRIFT, finding) for finding in module.verify(SOURCE_LOCK)
    ]


def git_dirty_paths() -> list[str]:
    completed = _run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=REPOSITORY_ROOT,
        timeout=30,
    )
    if completed.returncode != 0:
        return ["<git-status-failed>"]
    return [line for line in completed.stdout.splitlines() if line.strip()]


def release_policy_diagnostics(
    suites: Sequence[SuiteResult], *, dirty_paths: Sequence[str], release_mode: bool
) -> list[dict[str, str]]:
    if not release_mode:
        return []
    diagnostics: list[dict[str, str]] = []
    if dirty_paths:
        diagnostics.append(_diagnostic(EVID_DIRTY_SOURCE, "release mode requires a clean source tree"))
    for suite in suites:
        if suite.status != "pass" or suite.skipped_count or suite.not_run_count:
            diagnostics.append(
                _diagnostic(EVID_RELEASE_INCOMPLETE, f"{suite.suite_id} has a mandatory non-pass result")
            )
        if suite.warnings_count:
            diagnostics.append(
                _diagnostic(EVID_RELEASE_INCOMPLETE, f"{suite.suite_id} has unexpected warnings")
            )
        if suite.diagnostics:
            diagnostics.extend(suite.diagnostics)
    return diagnostics


def overall_result(suites: Sequence[SuiteResult], static_diagnostics: Sequence[dict[str, str]]) -> tuple[str, str]:
    if static_diagnostics or any(suite.fail_count or suite.status == "fail" for suite in suites):
        return "fail", "E0"
    if any(suite.status != "pass" or suite.skipped_count or suite.not_run_count for suite in suites):
        return "incomplete", "E0"
    return "pass", "E1"


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--self-check-only", action="store_true")
    args = parser.parse_args(argv)

    suites = [] if args.self_check_only else [
        run_compiler_suite(),
        run_product_suite(),
        run_typescript_suite(),
    ]
    static_diagnostics = [
        *verify_source_lock(),
        *validate_work_log(),
        *validate_overlap_map(),
        *validate_source_truth(),
        *reject_archived_current_evidence([]),
    ]
    dirty = git_dirty_paths()
    release_diagnostics = release_policy_diagnostics(
        suites, dirty_paths=dirty, release_mode=args.release
    )
    all_diagnostics = [*static_diagnostics, *release_diagnostics]
    status, evidence = overall_result(suites, all_diagnostics)
    if args.self_check_only and not all_diagnostics:
        status, evidence = "pass", "E0"
    payload = {
        "schema": "chw-navigator-baseline-manifest@1",
        "repository": {
            "root": ".",
            "branch": _run(["git", "branch", "--show-current"], cwd=REPOSITORY_ROOT, timeout=10).stdout.strip(),
            "commit": _run(["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, timeout=10).stdout.strip(),
            "dirty_paths": dirty,
        },
        "release_mode": args.release,
        "status": status,
        "evidence_level": evidence,
        "suites": [asdict(suite) for suite in suites],
        "diagnostics": all_diagnostics,
        "external_evidence": [
            {"check": "exact_target_cht_runtime", "status": "not_run", "level": "E4"},
            {"check": "representative_offline_sync", "status": "not_run", "level": "E5"},
            {"check": "clinical_governance_deployment_approval", "status": "not_supplied", "level": "E6"},
        ],
    }
    manifest = args.manifest if args.manifest.is_absolute() else REPOSITORY_ROOT / args.manifest
    _write_manifest(manifest, payload)
    print(f"WS0 baseline status={status} evidence={evidence} manifest={manifest}")
    return 0 if status in {"pass", "incomplete"} and not args.release else int(status != "pass")


if __name__ == "__main__":
    raise SystemExit(main())
