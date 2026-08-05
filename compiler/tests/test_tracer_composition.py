from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
EXAMPLES = ROOT / "examples" / "tracer"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.special_functions import calculate_gestational_age_naegele
from chw_navigator.cht_tasks import CHTTaskLoweringError
from chw_navigator.diagnostics import DiagnosticCode
from chw_navigator.tracer import build_tracer


class TracerCompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        root = Path(cls.temporary.name)
        cls.build = build_tracer(root / "bundle", evidence_manifest=root / "evidence.json")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_composition_preserves_unrelated_rule_and_is_idempotent(self) -> None:
        existing = (EXAMPLES / "existing-tasks.js").read_text(encoding="utf-8")
        composed = (self.build.output_dir / "composed-tasks.js").read_text(encoding="utf-8")
        unchanged_definition = existing.split("module.exports", 1)[0].rstrip()
        self.assertIn(unchanged_definition, composed)
        evidence = json.loads((self.build.output_dir / "task-composition.json").read_text(encoding="utf-8"))
        self.assertTrue(evidence["idempotent"])
        self.assertTrue(evidence["evidence"]["secondCompositionByteIdentical"])
        self.assertIn("CHW-NAVIGATOR-GENERATED-RULES-BEGIN", composed)
        self.assertIn("chw-nav-gestational-age-tracer-schedule-followup", composed)

    def test_rollback_restores_original_bytes(self) -> None:
        self.assertEqual(
            (EXAMPLES / "existing-tasks.js").read_bytes(),
            (self.build.output_dir / "rollback" / "tasks.js").read_bytes(),
        )

    def test_task_identity_trigger_and_due_policy_are_deterministic(self) -> None:
        first = (self.build.output_dir / "tasks.js").read_text(encoding="utf-8")
        self.assertIn('name: "chw-nav-gestational-age-tracer-schedule-followup"', first)
        self.assertIn('id: "chw-nav-gestational-age-tracer-schedule-followup-event"', first)
        self.assertIn("days: 7", first)
        self.assertIn("task_intent_schedule_followup.operation_id", first)
        self.assertIn("appliesTo: 'reports'", first)

    def test_changing_clinical_interval_changes_due_date_not_function_output(self) -> None:
        baseline = calculate_gestational_age_naegele(lmp_date="2026-01-01", reference_date="2026-01-09").to_dict()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = root / "examples"
            shutil.copytree(EXAMPLES, fixture)
            ir_path = fixture / "tracer.ir.json"
            payload = json.loads(ir_path.read_text(encoding="utf-8"))
            payload["decisions"]["d_followup_endpoint"]["rules"][2]["then"][
                "o_followup_due_days"
            ]["value"] = 9
            ir_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            changed = build_tracer(root / "bundle", evidence_manifest=root / "evidence.json", examples_dir=fixture)
            tasks = (changed.output_dir / "tasks.js").read_text(encoding="utf-8")
        self.assertIn("days: 9", tasks)
        self.assertEqual(
            baseline,
            calculate_gestational_age_naegele(lmp_date="2026-01-01", reference_date="2026-01-09").to_dict(),
        )

    def test_missing_decision_interval_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = root / "examples"
            shutil.copytree(EXAMPLES, fixture)
            ir_path = fixture / "tracer.ir.json"
            payload = json.loads(ir_path.read_text(encoding="utf-8"))
            del payload["decisions"]["d_followup_endpoint"]["rules"][2]["then"][
                "o_followup_due_days"
            ]
            ir_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(CHTTaskLoweringError) as raised:
                build_tracer(root / "bundle", evidence_manifest=root / "evidence.json", examples_dir=fixture)
        self.assertEqual(
            DiagnosticCode.CHT_TASK_SCHEDULE_UNSUPPORTED,
            raised.exception.diagnostics[0].code,
        )


if __name__ == "__main__":
    unittest.main()
