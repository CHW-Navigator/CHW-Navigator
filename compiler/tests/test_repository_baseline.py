from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


COMPILER_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = COMPILER_ROOT.parent
SCRIPT = COMPILER_ROOT / "scripts" / "verify_repository_baseline.py"
SPEC = importlib.util.spec_from_file_location("verify_repository_baseline", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RepositoryBaselineTests(unittest.TestCase):
    def test_unittest_parser_preserves_skip_reason(self) -> None:
        output = """test_one (tests.Sample.test_one) ... ok
test_two (tests.Sample.test_two) ... skipped 'official harness absent'
----------------------------------------------------------------------
Ran 2 tests in 0.100s

OK (skipped=1)
"""
        result = MODULE.parse_unittest_output(output, 0)
        self.assertEqual((1, 0, 1, 2), (result.pass_count, result.fail_count, result.skipped_count, result.total_count))
        self.assertEqual("official harness absent", result.skip_reasons[0]["reason"])
        self.assertEqual("skipped", result.status)

    def test_pytest_parser_recounts_failures_and_warnings(self) -> None:
        output = "4 failed, 78 passed, 2 warnings in 38.49s"
        result = MODULE.parse_pytest_output(output, 1)
        self.assertEqual((78, 4, 0, 82), (result.pass_count, result.fail_count, result.skipped_count, result.total_count))
        self.assertEqual(2, result.warnings_count)
        self.assertEqual("fail", result.status)

    def test_empty_test_output_emits_invalid_result_diagnostic(self) -> None:
        result = MODULE.parse_unittest_output("", 1)
        self.assertTrue(
            any(item["code"] == MODULE.EVID_INVALID_RESULT for item in result.diagnostics)
        )

    def test_node_parser_sums_package_ledgers_and_rejects_unexplained_skip(self) -> None:
        output = """ok 1 - works
# tests 1
# pass 1
# fail 0
# skipped 0
ok 1 - symlink # SKIP windows semantics
# tests 1
# pass 0
# fail 0
# skipped 1
"""
        result = MODULE.parse_node_test_output(output, 0)
        self.assertEqual((1, 0, 1, 2), (result.pass_count, result.fail_count, result.skipped_count, result.total_count))
        self.assertEqual("windows semantics", result.skip_reasons[0]["reason"])

    def test_archived_prompt12_evidence_is_rejected(self) -> None:
        diagnostics = MODULE.reject_archived_current_evidence(
            ["generated/prompt12-execution/chw-prompt12/reports/result.json"]
        )
        self.assertEqual(MODULE.EVID_ARCHIVE_AS_CURRENT, diagnostics[0]["code"])

    def test_work_log_requires_every_field(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "work-log.md"
            path.write_text("## WS0 - incomplete\n\n**Delivered:** something\n", encoding="utf-8")
            diagnostics = MODULE.validate_work_log(path)
        self.assertTrue(diagnostics)
        self.assertTrue(all(item["code"] == MODULE.EVID_WORK_LOG_INCOMPLETE for item in diagnostics))

    def test_overlap_map_rejects_empty_comparable_set(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "map.json"
            path.write_text(
                json.dumps(
                    {
                        "schema": "oracle-overlap-map@1",
                        "cases": [
                            {
                                "case_id": "x",
                                "comparability": "not_comparable",
                                "reason": "No shared semantic input exists.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            diagnostics = MODULE.validate_overlap_map(path)
        self.assertTrue(any("comparable set is empty" in item["message"] for item in diagnostics))
        self.assertTrue(all(item["code"] == MODULE.EVID_OVERLAP_INVALID for item in diagnostics))

    def test_source_truth_drift_has_stable_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "README.md"
            path.write_text("stale source claim\n", encoding="utf-8")
            diagnostics = MODULE.validate_source_truth({path: ("required current phrase",)})
        self.assertEqual(MODULE.EVID_SOURCE_TRUTH_DRIFT, diagnostics[0]["code"])

    def test_release_policy_rejects_dirty_warning_and_skip(self) -> None:
        suite = MODULE.SuiteResult(
            suite_id="sample", status="skipped", skipped_count=1, warnings_count=1
        )
        diagnostics = MODULE.release_policy_diagnostics(
            [suite], dirty_paths=[" M file"], release_mode=True
        )
        codes = {item["code"] for item in diagnostics}
        self.assertIn(MODULE.EVID_DIRTY_SOURCE, codes)
        self.assertIn(MODULE.EVID_RELEASE_INCOMPLETE, codes)

    def test_robocopy_exit_code_semantics_are_not_standard_process_semantics(self) -> None:
        for returncode in range(8):
            self.assertTrue(MODULE.robocopy_succeeded(returncode))
        self.assertFalse(MODULE.robocopy_succeeded(8))

    def test_root_independent_self_check_writes_valid_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            manifest = Path(raw) / "manifest.json"
            completed = subprocess.run(
                [
                    str(REPOSITORY_ROOT / ".venv" / "Scripts" / "python.exe"),
                    str(SCRIPT),
                    "--self-check-only",
                    "--manifest",
                    str(manifest),
                ],
                cwd=Path(raw),
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual("chw-navigator-baseline-manifest@1", payload["schema"])
        self.assertEqual("pass", payload["status"])


if __name__ == "__main__":
    unittest.main()
