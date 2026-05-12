from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.cli import main as cli_main
from test_support import create_test_run, reset_suite_runs


EXAMPLES = ROOT / "examples"


class QualityCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_suite_runs("quality_checks")

    def setUp(self) -> None:
        self.test_run = create_test_run(
            suite_name="quality_checks",
            test_name=self.id().split(".")[-1],
            purpose="Post-compile quality package tests for IR, XLSForm, Mermaid, and SMT outputs.",
            input_paths=(
                EXAMPLES / "pneumonia.ir.json",
                EXAMPLES / "pneumonia.cases.json",
            ),
        )

    def test_cli_quality_check_writes_package_and_flags_collection_path_gap(self) -> None:
        output_dir = self.test_run.outputs_dir / "quality_package"
        exit_code = cli_main(
            [
                "quality-check",
                str(EXAMPLES / "pneumonia.ir.json"),
                str(output_dir),
                "--patients",
                str(EXAMPLES / "pneumonia.cases.json"),
            ]
        )
        self.assertEqual(0, exit_code)
        report = json.loads((output_dir / "quality_report.json").read_text(encoding="utf-8"))
        self.assertIn("external_validator", report)
        self.assertEqual("XLSForm Online", report["external_validator"]["name"])
        self.assertTrue((output_dir / "quality_summary.md").exists())
        self.assertTrue((output_dir / "xlsform" / "survey.csv").exists())
        self.assertTrue((output_dir / "xlsform_roundtrip_proof" / "proof_summary.md").exists())
        blocker_messages = [item["message"] for item in report["release_blockers"]]
        self.assertTrue(any("no documented collection path" in message for message in blocker_messages))


if __name__ == "__main__":
    unittest.main()
