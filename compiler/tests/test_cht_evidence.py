from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.cht_evidence import (
    CHTEvidenceError,
    default_runner_records,
    exact_target_record,
    official_harness_record,
)
from chw_navigator.diagnostics import DiagnosticCode


class CHTEvidenceTests(unittest.TestCase):
    def test_profiles_are_separate_and_unrun_is_never_pass(self) -> None:
        records = default_runner_records()
        self.assertEqual({"4.22.0", "5.2.0"}, {item.profile for item in records})
        self.assertTrue(all(item.status == "not_run" and not item.executed for item in records))
        self.assertEqual(
            {"official_local_harness": "E3", "exact_target_runtime": "E4"},
            {item.check: item.evidence_level for item in records},
        )

    def test_e3_and_e4_pass_require_actual_execution(self) -> None:
        with self.assertRaises(CHTEvidenceError) as raised:
            official_harness_record("5.2.0", executed=False, passed=True, reason="not run")
        self.assertEqual(DiagnosticCode.EVIDENCE_RUNNER_INVALID, raised.exception.diagnostics[0].code)
        with self.assertRaises(CHTEvidenceError):
            exact_target_record("5.2.0", executed=False, passed=True, reason="not run")
        self.assertEqual(
            "pass",
            official_harness_record("5.2.0", executed=True, passed=True, reason="executed").status,
        )
        self.assertEqual(
            "pass",
            exact_target_record("5.2.0", executed=True, passed=True, reason="executed").status,
        )


if __name__ == "__main__":
    unittest.main()
