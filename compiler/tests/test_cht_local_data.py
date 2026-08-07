from __future__ import annotations

import unittest
from pathlib import Path
import sys
import tempfile
from xml.etree import ElementTree as ET
import shutil
import subprocess
import os


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.cht_backend import build_cht_lowering_plan
from chw_navigator.cht_backend import write_cht_adapter_bundle
from chw_navigator.cht_local_data import (
    CHTLocalDataLoweringError,
    parse_cht_local_data_registry,
)
from chw_navigator.clinical_ir import ClinicalIRDocument
from chw_navigator.cli import main as cli_main
from chw_navigator.diagnostics import DiagnosticCode
from chw_navigator.cht_xform import generate_cht_xform


BINDING_ID = "local.person.date_of_birth@1.0.0"


def _registry(*, value_type: str = "string"):
    return parse_cht_local_data_registry(
        {
            "schema_version": "cht-local-data-bindings@1.0.0",
            "target_cht_version": "4.22.0",
            "bindings": {
                BINDING_ID: {
                    "semantic_name": "date_of_birth",
                    "description": "The current person's recorded date of birth.",
                    "value_type": value_type,
                    "subject": "current_person",
                    "adapter": {"kind": "cht_contact_field", "path": "date_of_birth"},
                    "available_contexts": ["contact", "task"],
                    "freshness": {"policy": "immutable"},
                }
            },
        }
    )


def _document(*, source: str = BINDING_ID, fail_mode: str = "ask_if_missing", value_type: str = "string"):
    return ClinicalIRDocument.from_dict(
        {
            "metadata": {
                "ir_version": 1,
                "guideline_id": "local_data_demo",
                "sources": [{"source_id": "MANUAL"}, {"source_id": "CODEBOOK"}],
            },
            "variables": {
                "st_date_of_birth_h": {
                    "type": value_type,
                    "allowed_missingness": fail_mode == "soft_missing",
                    "multivalue": False,
                    "source_kind": "history",
                    "history_binding": {"record_key": source},
                    "provenance": [{"source_id": "CODEBOOK"}],
                }
            },
            "actions": {
                "a_read_date_of_birth": {
                    "kind": "read_local_data",
                    "source": source,
                    "outputs": ["st_date_of_birth_h"],
                    "mappings": [{"record_key": "value", "target_var": "st_date_of_birth_h"}],
                    "fail_mode": fail_mode,
                    "provenance": [{"source_id": "MANUAL"}, {"source_id": "CODEBOOK"}],
                }
            },
            "predicates": {},
            "phrases": {
                "m_date_of_birth_label": {
                    "entity_id": "st_date_of_birth_h",
                    "role": "label",
                    "texts": {"en": "Date of birth"},
                    "provenance": [{"source_id": "MANUAL"}],
                }
            },
            "decisions": {},
            "outputs": {},
            "invariants": {},
            "phrase_bindings": {},
        }
    )


class CHTLocalDataTests(unittest.TestCase):
    def test_rejects_invalid_registry_path(self) -> None:
        with self.assertRaises(CHTLocalDataLoweringError) as caught:
            parse_cht_local_data_registry(
                {
                    "schema_version": "cht-local-data-bindings@1.0.0",
                    "target_cht_version": "4.22.0",
                    "bindings": {
                        BINDING_ID: {
                            "semantic_name": "date_of_birth",
                            "description": "Date of birth",
                            "value_type": "string",
                            "subject": "current_person",
                            "adapter": {"kind": "cht_contact_field", "path": "date_of_birth)/bad"},
                            "available_contexts": ["contact"],
                            "freshness": {"policy": "immutable"},
                        }
                    },
                }
            )
        self.assertTrue(
            any(
                item.code is DiagnosticCode.CHT_LOCAL_DATA_REGISTRY_INVALID
                for item in caught.exception.diagnostics
            )
        )

    def test_lowers_contact_field_with_missing_fallback(self) -> None:
        plan = build_cht_lowering_plan(
            _document(),
            local_data_registry=_registry(),
            form_context="contact",
        )
        self.assertEqual(1, len(plan.local_data_reads))
        read = plan.local_data_reads[0]
        self.assertEqual("../inputs/contact/date_of_birth", read.source_xpath)
        self.assertEqual("local_fallback__st_date_of_birth_h", read.fallback_row)
        rows = plan.cht_xlsform.workbook.survey
        by_name = {row.name: row for row in rows}
        self.assertEqual("begin group", rows[0].type)
        self.assertEqual("inputs", rows[0].name)
        self.assertEqual("hidden", by_name["date_of_birth"].type)
        self.assertEqual("calculate", by_name["st_date_of_birth_h"].type)
        self.assertIn("${local_fallback__st_date_of_birth_h}", by_name["st_date_of_birth_h"].calculation)
        self.assertEqual("yes", by_name["local_fallback__st_date_of_birth_h"].required)
        self.assertEqual(
            "${local_status__st_date_of_birth_h} != 'available'",
            by_name["local_fallback__st_date_of_birth_h"].relevant,
        )

    def test_unknown_binding_fails_closed(self) -> None:
        with self.assertRaises(CHTLocalDataLoweringError) as caught:
            build_cht_lowering_plan(
                _document(source="local.person.unknown@1.0.0"),
                local_data_registry=_registry(),
            )
        self.assertTrue(
            any(
                item.code is DiagnosticCode.CHT_LOCAL_DATA_BINDING_UNBOUND
                for item in caught.exception.diagnostics
            )
        )

    def test_unavailable_launch_context_fails_closed(self) -> None:
        with self.assertRaises(CHTLocalDataLoweringError) as caught:
            build_cht_lowering_plan(
                _document(),
                local_data_registry=_registry(),
                form_context="reports",
            )
        self.assertTrue(
            any(
                item.code is DiagnosticCode.CHT_LOCAL_DATA_CONTEXT_UNAVAILABLE
                for item in caught.exception.diagnostics
            )
        )

    def test_type_mismatch_fails_closed(self) -> None:
        with self.assertRaises(CHTLocalDataLoweringError) as caught:
            build_cht_lowering_plan(
                _document(value_type="int"),
                local_data_registry=_registry(value_type="string"),
            )
        self.assertTrue(
            any(
                item.code is DiagnosticCode.CHT_LOCAL_DATA_TYPE_MISMATCH
                for item in caught.exception.diagnostics
            )
        )

    def test_freshness_limited_read_emits_stale_status(self) -> None:
        binding_id = "local.person.last_weight_kg@1.0.0"
        registry = parse_cht_local_data_registry(
            {
                "schema_version": "cht-local-data-bindings@1.0.0",
                "target_cht_version": "4.22.0",
                "bindings": {
                    binding_id: {
                        "semantic_name": "last_weight_kg",
                        "description": "Most recently recorded weight and its observation date.",
                        "value_type": "decimal",
                        "unit": "kg",
                        "subject": "current_person",
                        "adapter": {"kind": "cht_contact_summary", "path": "last_weight_kg"},
                        "available_contexts": ["contact"],
                        "freshness": {
                            "policy": "max_age_days",
                            "recorded_at_path": "last_weight_date",
                            "max_age_days": 30,
                        },
                    }
                },
            }
        )
        document = ClinicalIRDocument.from_dict(
            {
                "metadata": {"ir_version": 1, "guideline_id": "weight", "sources": [{"source_id": "S"}]},
                "variables": {
                    "st_weight_kg_h": {
                        "type": "decimal",
                        "unit": "kg",
                        "allowed_missingness": True,
                        "multivalue": False,
                        "source_kind": "history",
                        "history_binding": {"record_key": binding_id, "freshness_max_age_days": 30},
                        "provenance": [{"source_id": "S"}],
                    },
                    "st_weight_recorded_at_h": {
                        "type": "string",
                        "allowed_missingness": True,
                        "multivalue": False,
                        "source_kind": "history",
                        "history_binding": {"record_key": binding_id},
                        "provenance": [{"source_id": "S"}],
                    },
                },
                "actions": {
                    "a_read_weight": {
                        "kind": "read_local_data",
                        "source": binding_id,
                        "outputs": ["st_weight_kg_h", "st_weight_recorded_at_h"],
                        "mappings": [{
                            "record_key": "value",
                            "target_var": "st_weight_kg_h",
                            "recorded_at_target_var": "st_weight_recorded_at_h",
                        }],
                        "fail_mode": "soft_missing",
                        "provenance": [{"source_id": "S"}],
                    }
                },
                "predicates": {}, "phrases": {}, "decisions": {}, "outputs": {},
                "invariants": {}, "phrase_bindings": {},
            }
        )
        plan = build_cht_lowering_plan(document, local_data_registry=registry)
        rows = {row.name: row for row in plan.cht_xlsform.workbook.survey}
        self.assertIn("cht:difference-in-days", rows["local_status__st_weight_kg_h"].calculation)
        self.assertIn("'stale'", rows["local_status__st_weight_kg_h"].calculation)
        self.assertEqual(
            "instance('contact-summary')/context/last_weight_date",
            rows["st_weight_recorded_at_h"].calculation,
        )
        xform = generate_cht_xform(plan.cht_xlsform)
        self.assertIn('xmlns:cht="https://communityhealthtoolkit.org"', xform)
        self.assertIn("cht:difference-in-days", xform)

    def test_cli_writes_executable_local_data_form_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = cli_main(
                [
                    "build-cht",
                    str(ROOT / "examples" / "cht_local_data_demo.ir.json"),
                    str(ROOT / "examples" / "cht-task-bindings.json"),
                    directory,
                    "--local-data-bindings",
                    str(ROOT / "examples" / "cht-local-data-bindings.json"),
                    "--form-context",
                    "contact",
                ]
            )
            self.assertEqual(0, result)
            survey = (
                Path(directory)
                / "forms"
                / "app"
                / "registered_local_data_demo.xlsform"
                / "survey.csv"
            )
            self.assertTrue(survey.exists())
            text = survey.read_text(encoding="utf-8")
            self.assertIn('"begin group","inputs"', text)
            self.assertIn("../inputs/contact/date_of_birth", text)
            self.assertTrue((Path(directory) / "cht_local_data_plan.json").exists())
            xform = Path(directory) / "forms" / "app" / "registered_local_data_demo.xml"
            self.assertTrue(xform.exists())
            root = ET.fromstring(xform.read_text(encoding="utf-8"))
            self.assertTrue(root.tag.endswith("html"))
            xml = xform.read_text(encoding="utf-8")
            self.assertIn('nodeset="/data/inputs/contact/date_of_birth"', xml)
            self.assertIn('calculate="if(string-length', xml)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the official CHT harness test")
    def test_generated_xform_reads_contact_and_uses_missing_fallback_in_official_harness(self) -> None:
        harness_root = ROOT.parent / "Testing" / "Aaron" / "cht-harness"
        harness_module = harness_root / "node_modules" / "cht-conf-test-harness"
        if not harness_module.exists():
            self.skipTest("Run npm ci in Testing/Aaron/cht-harness to install the official harness")
        browser_candidates = (
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        )
        browser = next((path for path in browser_candidates if path.exists()), None)
        if browser is None:
            self.skipTest("The official CHT harness requires an installed Chrome-compatible browser")
        xsltproc = shutil.which("xsltproc")
        if xsltproc is None:
            bundled_xsltproc = Path(r"C:\msys64\usr\bin\xsltproc.exe")
            if not bundled_xsltproc.exists():
                self.skipTest("The official CHT harness requires xsltproc")
            xsltproc = str(bundled_xsltproc)
        try:
            probe = subprocess.run(
                [xsltproc, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            self.skipTest("The installed xsltproc is not executable by the official CHT harness")
        if probe.returncode != 0:
            self.skipTest("The installed xsltproc is not executable by the official CHT harness")
        harness_env = dict(os.environ)
        harness_env["PATH"] = str(Path(xsltproc).parent) + os.pathsep + harness_env.get("PATH", "")
        with tempfile.TemporaryDirectory() as directory:
            plan = build_cht_lowering_plan(
                _document(),
                local_data_registry=_registry(),
                form_context="contact",
            )
            artifacts = write_cht_adapter_bundle(plan, directory)
            self.assertIsNotNone(artifacts.form_xform_path)
            result = subprocess.run(
                [
                    "node",
                    str(ROOT / "tests" / "cht_local_data_harness_runner.js"),
                    str(harness_module),
                    str(harness_root / "app_settings.json"),
                    str(artifacts.form_xform_path.parent),
                    artifacts.form_xform_path.stem,
                    str(browser),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=90,
                env=harness_env,
            )
            harness_output = result.stderr or result.stdout
            # MSYS can report a successful --version yet fail to create its
            # POSIX mount table when the harness starts xsltproc. This is an
            # unavailable official-harness environment, not evidence that the
            # generated XForm failed conversion. Keep it explicitly not_run.
            if (
                result.returncode != 0
                and "xsltproc returned code" in harness_output
                and "fatal error - add_item" in harness_output
            ):
                self.skipTest("The installed MSYS xsltproc cannot execute inside the official CHT harness")
            self.assertEqual(0, result.returncode, harness_output)


if __name__ == "__main__":
    unittest.main()
