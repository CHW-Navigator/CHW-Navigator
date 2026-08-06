from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.cht_task_composer import (
    CHTTaskCompositionError,
    compose_tasks_js,
    extract_task_identities,
)
from chw_navigator.cht_tasks import generate_tasks_js, load_cht_task_bindings, build_task_intent_plans
from chw_navigator.clinical_ir import ClinicalIRDocument
from chw_navigator.cht_backend import build_cht_lowering_plan
from chw_navigator.diagnostics import DiagnosticCode


EXAMPLES = ROOT / "examples" / "tracer"


class PythonTaskComposerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        document = ClinicalIRDocument.from_dict(
            __import__("json").loads((EXAMPLES / "tracer.ir.json").read_text(encoding="utf-8"))
        )
        bindings = load_cht_task_bindings(EXAMPLES / "task-bindings.json")
        plan = build_cht_lowering_plan(document, task_bindings=bindings)
        cls.generated = generate_tasks_js(plan.task_intent_plans)
        cls.existing = (EXAMPLES / "existing-tasks.js").read_text(encoding="utf-8")

    def test_preserves_existing_source_and_is_byte_idempotent(self) -> None:
        result = compose_tasks_js(self.existing, self.generated)
        unchanged = self.existing.split("module.exports", 1)[0].rstrip()
        self.assertIn(unchanged, result.content)
        self.assertTrue(result.evidence["second_composition_byte_identical"])
        second = compose_tasks_js(result.content, self.generated, previous_state=result.state)
        self.assertEqual(result.content, second.content)

    def test_identity_collision_fails_closed(self) -> None:
        generated_name = extract_task_identities(self.generated)[0].name
        colliding = self.existing.replace(
            "existing-unrelated-supervision-task", generated_name
        )
        with self.assertRaises(CHTTaskCompositionError) as raised:
            compose_tasks_js(colliding, self.generated)
        self.assertEqual(DiagnosticCode.CHT_COMPOSITION_INVALID, raised.exception.diagnostics[0].code)

    def test_unmanaged_spread_and_untrusted_managed_block_fail(self) -> None:
        spread = self.existing.replace(
            "module.exports = [unrelatedSupervisionRule]",
            "module.exports = [unrelatedSupervisionRule, ...otherRules]",
        )
        with self.assertRaises(CHTTaskCompositionError):
            compose_tasks_js(spread, self.generated)
        first = compose_tasks_js(self.existing, self.generated)
        with self.assertRaises(CHTTaskCompositionError):
            compose_tasks_js(first.content, self.generated)


if __name__ == "__main__":
    unittest.main()
