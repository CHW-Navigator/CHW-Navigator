from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SRC = ROOT / "src"
for path in (SCRIPTS, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from verify_diagnostic_coverage import coverage_gaps


class DiagnosticCodeCoverageTests(unittest.TestCase):
    def test_every_declared_code_is_emitted_and_asserted(self) -> None:
        missing_emission, missing_assertion = coverage_gaps()
        self.assertEqual([], missing_emission)
        self.assertEqual([], missing_assertion)


if __name__ == "__main__":
    unittest.main()
