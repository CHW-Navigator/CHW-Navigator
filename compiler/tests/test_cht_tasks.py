from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.cht_backend import build_cht_lowering_plan, write_cht_adapter_bundle
from chw_navigator.cli import main as cli_main
from chw_navigator.cht_tasks import (
    CHTTaskLoweringError,
    generate_tasks_js,
    parse_cht_task_bindings,
)
from chw_navigator.clinical_ir import ClinicalIRDocument
from chw_navigator.diagnostics import DiagnosticCode
from test_support import create_test_run, reset_suite_runs


def _document(*, due_in_days: int | None = 3, due_at_expr: dict[str, object] | None = None) -> ClinicalIRDocument:
    action: dict[str, object] = {
        "kind": "create_task",
        "outputs": [],
        "when": {"kind": "var", "id": "v_followup_needed"},
        "task_type": "clinical_followup",
        "priority": "routine",
        "assignee_role": "chw",
        "message_key": "m_schedule_followup",
        "provenance": [{"source_id": "SRC", "location": "task-table:1"}],
    }
    if due_in_days is not None:
        action["due_in_days"] = due_in_days
    if due_at_expr is not None:
        action["due_at_expr"] = due_at_expr
    return ClinicalIRDocument.from_dict(
        {
            "metadata": {
                "ir_version": 1,
                "guideline_id": "chw_nav_task_intent_schedule_followup_schedule_followup",
                "sources": [{"source_id": "SRC"}],
            },
            "variables": {
                "v_followup_needed": {
                    "type": "bool",
                    "allowed_missingness": False,
                    "multivalue": False,
                    "source_kind": "encounter_input",
                    "provenance": [{"source_id": "SRC"}],
                }
            },
            "predicates": {},
            "actions": {"a_schedule_followup": action},
            "phrases": {
                "m_schedule_followup": {
                    "entity_id": "a_schedule_followup",
                    "role": "message",
                    "texts": {"en": "Schedule follow-up"},
                    "provenance": [{"source_id": "SRC"}],
                }
            },
            "outputs": {},
            "decisions": {},
            "invariants": {},
            "phrase_bindings": {},
        }
    )


def _bindings(
    *,
    task_type: str = "clinical_followup",
    assignee_role: str = "chw",
    target_cht_version: str = "4.22.0",
):
    return parse_cht_task_bindings(
        {
            "schema_version": "cht-task-bindings@1.0.0",
            "target_cht_version": target_cht_version,
            "task_types": {
                task_type: {
                    "source_message_key": "m_schedule_followup",
                    "title_key": f"task.{task_type}.title",
                    "followup_form": "registered_encounter_followup",
                    "permission_key": "can_schedule_clinical_followup",
                    "icon": "icon-healthcare-followup",
                    "start_days": 0,
                    "end_days": 2,
                    "source_priority": "routine",
                    "assignee_role": assignee_role,
                    "priority": {"level": 1, "label": "task.priority.clinical_followup"},
                }
            },
        }
    )


class CHTTaskLoweringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_suite_runs("cht_tasks")

    def setUp(self) -> None:
        self.test_run = create_test_run(
            suite_name="cht_tasks",
            test_name=self.id().split(".")[-1],
            purpose="CHT create_task to form/task-rule integration tests.",
        )

    def test_requires_explicit_task_binding(self) -> None:
        with self.assertRaises(CHTTaskLoweringError) as caught:
            build_cht_lowering_plan(_document())
        self.assertEqual(DiagnosticCode.CHT_TASK_TYPE_UNBOUND, caught.exception.diagnostics[0].code)

    def test_rejects_invalid_binding_contract(self) -> None:
        with self.assertRaises(CHTTaskLoweringError) as caught:
            parse_cht_task_bindings(
                {
                    "schema_version": "cht-task-bindings@1.0.0",
                    "target_cht_version": "4.22.0",
                    "task_types": {"bad-name": {}},
                }
            )
        self.assertTrue(
            any(item.code is DiagnosticCode.CHT_TASK_BINDING_INVALID for item in caught.exception.diagnostics)
        )

    def test_rejects_unsupported_absolute_schedule_and_role(self) -> None:
        with self.assertRaises(CHTTaskLoweringError) as caught:
            build_cht_lowering_plan(
                _document(due_in_days=None, due_at_expr={"kind": "literal", "value": 10}),
                task_bindings=_bindings(assignee_role="supervisor"),
            )
        self.assertTrue(
            any(item.code is DiagnosticCode.CHT_TASK_SCHEDULE_UNSUPPORTED for item in caught.exception.diagnostics)
        )

    def test_rejects_task_identity_collision(self) -> None:
        document = _document()
        first = document.actions["a_schedule_followup"]
        duplicate = type(first)(
            id="schedule_followup",
            kind=first.kind,
            outputs=list(first.outputs),
            when=first.when,
            task_type=first.task_type,
            due_in_days=first.due_in_days,
            priority=first.priority,
            assignee_role=first.assignee_role,
            message_key=first.message_key,
            provenance=list(first.provenance),
        )
        document.actions[duplicate.id] = duplicate
        with self.assertRaises(CHTTaskLoweringError) as caught:
            build_cht_lowering_plan(document, task_bindings=_bindings())
        self.assertTrue(
            any(item.code is DiagnosticCode.CHT_TASK_IDENTITY_COLLISION for item in caught.exception.diagnostics)
        )

    def test_writes_matching_task_fields_tasks_js_and_manifest(self) -> None:
        plan = build_cht_lowering_plan(_document(), task_bindings=_bindings())
        artifacts = write_cht_adapter_bundle(plan, self.test_run.outputs_dir / "bundle")
        self.assertIsNotNone(artifacts.tasks_js_path)
        self.assertIsNotNone(artifacts.form_survey_path)
        source = artifacts.tasks_js_path.read_text(encoding="utf-8")
        survey = artifacts.form_survey_path.read_text(encoding="utf-8")
        self.assertIn('name: "chw-nav-chw-nav-task-intent-schedule-followup-schedule-followup-schedule-followup"', source)
        self.assertIn('appliesToType: ["chw_nav_task_intent_schedule_followup_schedule_followup"]', source)
        self.assertIn('Utils.getField(report, "task_intent_schedule_followup.required")', source)
        self.assertIn("days: 3", source)
        self.assertIn("start: 0", source)
        self.assertIn("end: 2", source)
        self.assertIn('"begin group","task_intent_schedule_followup"', survey)
        self.assertIn('"calculate","required"', survey)
        self.assertIn("v_followup_needed", survey)
        self.assertIn('"calculate","operation_id"', survey)
        self.assertIn("/data/meta/instanceID", survey)
        manifest = json.loads(artifacts.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual("@chw-navigator/cht-integration task-composer@1", manifest["task_composer_contract"])
        self.assertTrue(any(item["path"] == "tasks.js" for item in manifest["files"]))
        self.assertEqual(["can_schedule_clinical_followup"], manifest["deployment_requirements"]["permissions"])
        self.assertIn("task.clinical_followup.title", manifest["deployment_requirements"]["translation_keys"])

    def test_reviewed_versions_are_separate_even_when_task_syntax_matches(self) -> None:
        plan_422 = build_cht_lowering_plan(_document(), task_bindings=_bindings(target_cht_version="4.22.0"))
        plan_52 = build_cht_lowering_plan(_document(), task_bindings=_bindings(target_cht_version="5.2.0"))
        self.assertEqual("4.22.0", plan_422.target_cht_version)
        self.assertEqual("5.2.0", plan_52.target_cht_version)
        self.assertEqual(generate_tasks_js(plan_422.task_intent_plans), generate_tasks_js(plan_52.task_intent_plans))

    def test_cli_build_cht_connects_ir_form_fields_and_tasks_js(self) -> None:
        output_dir = self.test_run.outputs_dir / "cli_bundle"
        result = cli_main(
            [
                "build-cht",
                str(ROOT / "examples" / "cht_task_demo.ir.json"),
                str(ROOT / "examples" / "cht-task-bindings.json"),
                str(output_dir),
            ]
        )
        self.assertEqual(0, result)
        self.assertTrue((output_dir / "tasks.js").exists())
        survey = output_dir / "forms" / "app" / "registered_encounter_form.xlsform" / "survey.csv"
        self.assertTrue(survey.exists())
        self.assertIn("task_intent_schedule_followup", survey.read_text(encoding="utf-8"))

    @unittest.skipUnless(shutil.which("node"), "Node.js is required to execute generated tasks.js")
    def test_generated_rule_executes_duplicate_suppression_and_resolution(self) -> None:
        plan = build_cht_lowering_plan(_document(), task_bindings=_bindings())
        tasks_path = self.test_run.outputs_dir / "tasks.js"
        tasks_path.write_text(generate_tasks_js(plan.task_intent_plans), encoding="utf-8")
        script = r"""
const path = require('node:path');
global.Utils = {
  getField(report, fieldPath) { return fieldPath.split('.').reduce((value, key) => value == null ? undefined : value[key], report.fields); },
  addDate(date, days) { const result = new Date(date.getTime()); result.setUTCDate(result.getUTCDate() + days); return result; }
};
const tasks = require(path.resolve(process.argv[1]));
const group = { required: 'true', task_type: 'clinical_followup', operation_id: 'wf-1::schedule_followup' };
const first = { _id: 'a', form: 'chw_nav_task_intent_schedule_followup_schedule_followup', reported_date: 100, fields: { task_intent_schedule_followup: group } };
const duplicate = { _id: 'b', form: first.form, reported_date: 101, fields: { task_intent_schedule_followup: group } };
if (!tasks[0].appliesIf({ reports: [duplicate, first] }, first)) process.exit(2);
if (tasks[0].appliesIf({ reports: [duplicate, first] }, duplicate)) process.exit(3);
const due = new Date(Date.UTC(2026, 0, 4));
const event = tasks[0].events[0];
const followup = { _id: 'f', form: 'registered_encounter_followup', reported_date: due.getTime(), fields: { source_task_operation_id: group.operation_id, source_task_event_id: event.id } };
if (!tasks[0].resolvedIf({ reports: [followup] }, first, event, due)) process.exit(4);
"""
        result = subprocess.run(
            ["node", "-e", script, str(tasks_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for TypeScript composer compatibility")
    def test_reviewed_typescript_composer_accepts_python_tasks(self) -> None:
        integration_module = (
            ROOT.parents[1]
            / "generated"
            / "prompt12-execution"
            / "chw-prompt12"
            / "packages"
            / "cht-integration"
            / "dist"
            / "index.js"
        )
        if not integration_module.exists():
            self.skipTest("reviewed TypeScript integration package is not present in this checkout")
        plan = build_cht_lowering_plan(_document(), task_bindings=_bindings())
        tasks_path = self.test_run.outputs_dir / "tasks.js"
        tasks_path.write_text(generate_tasks_js(plan.task_intent_plans), encoding="utf-8")
        script = r"""
const fs = require('node:fs');
const { pathToFileURL } = require('node:url');
(async () => {
  const integration = await import(pathToFileURL(process.argv[1]).href);
  const generated = fs.readFileSync(process.argv[2], 'utf8');
  const result = integration.composeTasksJs("'use strict';\nmodule.exports = [];\n", generated, 'tasks.js');
  if (result.diagnostics.some(item => item.severity === 'error')) throw new Error(JSON.stringify(result.diagnostics));
  if (!result.content.includes('CHW-NAVIGATOR-GENERATED-RULES-BEGIN')) throw new Error('managed block missing');
  if (!result.content.includes('chw-nav-chw-nav-task-intent')) throw new Error('generated task missing');
})().catch(error => { console.error(error); process.exit(1); });
"""
        result = subprocess.run(
            ["node", "-e", script, str(integration_module), str(tasks_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
