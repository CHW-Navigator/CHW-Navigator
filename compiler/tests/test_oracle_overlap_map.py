from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


COMPILER_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = COMPILER_ROOT.parent
SRC = COMPILER_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.special_functions import (
    calculate_gestational_age_from_lmp,
    calculate_gestational_age_naegele,
)


MAP_PATH = COMPILER_ROOT / "integration" / "oracle-overlap-map.json"
SOURCE_LOCK_PATH = COMPILER_ROOT / "integration" / "prompt12-source-lock.json"


def _source_root() -> Path:
    lock = json.loads(SOURCE_LOCK_PATH.read_text(encoding="utf-8"))
    return (REPOSITORY_ROOT / lock["source"]["workspace_relative_path"]).resolve()


def _normalize_python(case: dict) -> dict:
    if case["python_entrypoint"].endswith("calculate_gestational_age_naegele"):
        result = calculate_gestational_age_naegele(**case["input"]).to_dict()
        normalized = {"status": result["status"]}
        if "technical" in result:
            technical = result["technical"]
            normalized["technical"] = {
                "gestational_age_weeks": round(
                    technical["ga_weeks"] + technical["ga_days_remainder"] / 7,
                    1,
                ),
                "estimated_delivery_date": technical["edd"],
            }
        return normalized
    result = calculate_gestational_age_from_lmp(**case["input"]).to_dict()
    normalized = {"status": result["status"]}
    if "technical" in result:
        normalized["technical"] = result["technical"]
    return normalized


def _normalize_typescript(case: dict) -> dict:
    node = shutil.which("node")
    if node is None:
        raise AssertionError("Comparable oracle cases require Node.js; result is not_run, not pass")
    module_path = _source_root() / case["typescript_entrypoint"].split("#", 1)[0]
    if not module_path.is_file():
        raise AssertionError(f"Comparable TypeScript entrypoint is absent: {module_path}")
    script = """
import { pathToFileURL } from 'node:url';
let raw = '';
for await (const chunk of process.stdin) raw += chunk;
const input = JSON.parse(raw);
const module = await import(pathToFileURL(process.argv[1]).href);
const result = module.calculateGestationalAgeFromLmp({
  lmpDate: input.lmp_date,
  asOfDate: input.as_of_date ?? input.reference_date,
  functionVersion: input.function_version ?? '1.0.0',
  referenceDataVersion: input.reference_data_version ?? 'calendar-280-day-v1'
});
console.log(JSON.stringify(result));
"""
    completed = subprocess.run(
        [node, "--input-type=module", "-e", script, str(module_path)],
        input=json.dumps(case["input"]),
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
    result = json.loads(completed.stdout)
    normalized = {"status": result["status"]}
    if "technical" in result:
        technical = result["technical"]
        normalized["technical"] = {
            "gestational_age_weeks": technical["gestationalAgeWeeks"],
            "estimated_delivery_date": technical["estimatedDeliveryDate"],
        }
    return normalized


class OracleOverlapMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(MAP_PATH.read_text(encoding="utf-8"))

    def test_map_has_non_empty_executable_comparable_set(self) -> None:
        comparable = [
            case for case in self.payload["cases"] if case["comparability"] == "comparable"
        ]
        self.assertTrue(comparable)
        for case in comparable:
            self.assertEqual(_normalize_python(case), _normalize_typescript(case), case["case_id"])

    def test_not_comparable_reasons_are_semantic_and_non_empty(self) -> None:
        for case in self.payload["cases"]:
            if case["comparability"] != "not_comparable":
                continue
            reason = case.get("reason")
            self.assertIsInstance(reason, str)
            self.assertTrue(reason.strip())
            self.assertNotIn("not implemented", reason.lower())

    def test_comparable_set_cannot_shrink_without_demotions(self) -> None:
        previous = subprocess.run(
            ["git", "show", "HEAD:compiler/integration/oracle-overlap-map.json"],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if previous.returncode != 0:
            return
        old_payload = json.loads(previous.stdout)
        old_comparable = {
            case["case_id"]
            for case in old_payload["cases"]
            if case["comparability"] == "comparable"
        }
        new_comparable = {
            case["case_id"]
            for case in self.payload["cases"]
            if case["comparability"] == "comparable"
        }
        demotions = {
            item["case_id"]: item.get("reason", "") for item in self.payload.get("demotions", [])
        }
        for case_id in old_comparable - new_comparable:
            self.assertIn(case_id, demotions)
            self.assertTrue(demotions[case_id].strip())


if __name__ == "__main__":
    unittest.main()
