from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.catalogs import compose_document_from_catalogs
from chw_navigator.staged_lint import (
    lint_ir_document,
    lint_mermaid_artifact,
    lint_smt_artifact,
    lint_xlsform_artifacts,
    preflight_source_artifact,
)
from chw_navigator.xlsform_backend import build_xlsform, write_xlsform_csvs
from test_support import create_test_run, reset_suite_runs


EXAMPLES = ROOT / "examples"


class StagedLintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_suite_runs("staged_lint")

    def setUp(self) -> None:
        self.test_run = create_test_run(
            suite_name="staged_lint",
            test_name=self.id().split(".")[-1],
            purpose="Validate staged source, IR, XLSForm, Mermaid, and SMT lint helpers.",
            input_paths=(EXAMPLES / "pneumonia.ir.json", EXAMPLES / "pneumonia.dmn"),
        )

    def test_preflight_variable_catalog_detects_bad_measurement_limits(self) -> None:
        path = self.test_run.inputs_dir / "variables.csv"
        path.write_text(
            "\n".join(
                [
                    "id,type,domain_min,domain_max,remeasure_min,dont_allow_min,dont_allow_max,allowed_missingness,multivalue,provenance_source_id",
                    "v_temp_c_x10,int,250,450,355,250,450,false,false,CATALOG_TEST",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        report = preflight_source_artifact("variable_catalog", path)
        self.assertFalse(report.ok)
        self.assertTrue(any("remeasure_min and remeasure_max" in item.message for item in report.issues))

    def test_preflight_dmn_accepts_supported_subset(self) -> None:
        report = preflight_source_artifact("dmn", EXAMPLES / "pneumonia.dmn")
        self.assertTrue(report.ok)
        self.assertGreaterEqual(report.metadata.get("decision_count", 0), 1)

    def test_ir_xlsform_mermaid_and_smt_lint_on_catalog_example(self) -> None:
        document = compose_document_from_catalogs(
            EXAMPLES / "catalogs" / "pneumonia.metadata.json",
            EXAMPLES / "catalogs" / "pneumonia.variables.csv",
            EXAMPLES / "catalogs" / "pneumonia.predicates.json",
            EXAMPLES / "catalogs" / "pneumonia.phrases.csv",
        )
        ir_report = lint_ir_document(document, source_path=str(EXAMPLES / "catalogs" / "pneumonia.metadata.json"))
        self.assertTrue(ir_report.ok)

        built = build_xlsform(document)
        output_dir = self.test_run.outputs_dir / "xlsform"
        survey_path, choices_path, _ = write_xlsform_csvs(built, str(output_dir))
        xlsform_report = lint_xlsform_artifacts(survey_path, choices_path)
        self.assertTrue(xlsform_report.ok)

        mermaid_report = lint_mermaid_artifact(document)
        self.assertTrue(mermaid_report.ok)

        smt_report = lint_smt_artifact(document)
        self.assertIn(smt_report.ok, {True, False})
        self.assertEqual("smt2", smt_report.artifact_type)

    def test_mermaid_lint_flags_missing_graph_structure(self) -> None:
        document = compose_document_from_catalogs(
            EXAMPLES / "catalogs" / "pneumonia.metadata.json",
            EXAMPLES / "catalogs" / "pneumonia.variables.csv",
            EXAMPLES / "catalogs" / "pneumonia.predicates.json",
            EXAMPLES / "catalogs" / "pneumonia.phrases.csv",
        )
        report = lint_mermaid_artifact(document, candidate_text="classDef variable fill:#fff\nA[Start")
        self.assertFalse(report.ok)
        messages = [issue.message for issue in report.issues]
        self.assertTrue(any("missing graph declaration" in message for message in messages))
        self.assertTrue(any("no edges defined" in message for message in messages))

    def test_mermaid_lint_reports_render_backend_metadata(self) -> None:
        document = compose_document_from_catalogs(
            EXAMPLES / "catalogs" / "pneumonia.metadata.json",
            EXAMPLES / "catalogs" / "pneumonia.variables.csv",
            EXAMPLES / "catalogs" / "pneumonia.predicates.json",
            EXAMPLES / "catalogs" / "pneumonia.phrases.csv",
        )
        report = lint_mermaid_artifact(document)
        self.assertIn(report.metadata.get("render_backend"), {"mmdc", "python_only"})
        if report.metadata.get("render_backend") == "python_only":
            self.assertTrue(any(issue.path == "mermaid.render" and issue.level == "WARNING" for issue in report.issues))

    def test_preflight_patient_cases_detects_duplicate_names(self) -> None:
        path = self.test_run.inputs_dir / "cases.json"
        path.write_text(
            json.dumps(
                {
                    "cases": [
                        {"name": "dup", "values": {"v_age_months": 1}},
                        {"name": "dup", "values": {"v_age_months": 2}},
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )
        report = preflight_source_artifact("patient_cases", path)
        self.assertFalse(report.ok)
        self.assertTrue(any("duplicate case name" in item.message for item in report.issues))


if __name__ == "__main__":
    unittest.main()
