"""Fail when a declared diagnostic is neither emitted by source nor asserted by a test."""

from __future__ import annotations

from pathlib import Path
import re
import sys


COMPILER_ROOT = Path(__file__).resolve().parents[1]
SRC = COMPILER_ROOT / "src" / "chw_navigator"
TESTS = COMPILER_ROOT / "tests"
if str(SRC.parent) not in sys.path:
    sys.path.insert(0, str(SRC.parent))

from chw_navigator.diagnostics import DiagnosticCode


def _contains_reference(paths: list[Path], member: str) -> bool:
    pattern = re.compile(rf"\bDiagnosticCode\.{re.escape(member)}\b")
    return any(pattern.search(path.read_text(encoding="utf-8")) for path in paths)


def coverage_gaps() -> tuple[list[str], list[str]]:
    source_paths = [path for path in SRC.glob("*.py") if path.name != "diagnostics.py"]
    test_paths = [path for path in TESTS.glob("test_*.py") if path.name != "test_diagnostic_code_coverage.py"]
    missing_emission = [member.name for member in DiagnosticCode if not _contains_reference(source_paths, member.name)]
    missing_assertion = [member.name for member in DiagnosticCode if not _contains_reference(test_paths, member.name)]
    return missing_emission, missing_assertion


def main() -> int:
    missing_emission, missing_assertion = coverage_gaps()
    if missing_emission:
        print(f"ERROR: diagnostic codes not emitted by source: {', '.join(missing_emission)}", file=sys.stderr)
    if missing_assertion:
        print(f"ERROR: diagnostic codes not asserted by tests: {', '.join(missing_assertion)}", file=sys.stderr)
    if missing_emission or missing_assertion:
        return 1
    print(f"Diagnostic coverage verified for {len(DiagnosticCode)} declared codes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
