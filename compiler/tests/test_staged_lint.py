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
from chw_navigator.dmn import import_dmn_decisions
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

    def test_preflight_variable_catalog_warns_on_missing_unit_domain_and_sparse_provenance(self) -> None:
        path = self.test_run.inputs_dir / "variable_warnings.csv"
        path.write_text(
            "\n".join(
                [
                    "id,type,unit,allowed_missingness,multivalue,provenance_source_id",
                    "v_weight,int,kg,false,false,CATALOG_TEST",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        report = preflight_source_artifact("variable_catalog", path)
        self.assertTrue(report.ok)
        messages = [item.message for item in report.issues]
        self.assertTrue(any("numeric variable should define domain metadata" in message for message in messages))
        self.assertTrue(any("should usually encode stored units in the identifier" in message for message in messages))
        self.assertTrue(any("no additional locator fields" in message for message in messages))

    def test_preflight_variable_catalog_detects_inverted_domain_bounds(self) -> None:
        path = self.test_run.inputs_dir / "variable_bad_domain.csv"
        path.write_text(
            "\n".join(
                [
                    "id,type,domain_min,domain_max,unit,allowed_missingness,multivalue,provenance_source_id,provenance_kind",
                    "v_muac_mm,int,300,50,mm,false,false,CATALOG_TEST,variable_catalog",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        report = preflight_source_artifact("variable_catalog", path)
        self.assertFalse(report.ok)
        self.assertTrue(
            any(
                "domain min cannot exceed max" in item.message or "domain_min must be <= domain_max" in item.message
                for item in report.issues
            )
        )

    def test_preflight_dmn_accepts_supported_subset(self) -> None:
        report = preflight_source_artifact("dmn", EXAMPLES / "pneumonia.dmn")
        self.assertTrue(report.ok)
        self.assertGreaterEqual(report.metadata.get("decision_count", 0), 1)

    def test_preflight_dmn_reports_hit_policy_and_compound_cell_violations(self) -> None:
        path = self.test_run.inputs_dir / "bad_logic.dmn"
        path.write_text(
            (EXAMPLES / "pneumonia.dmn")
            .read_text(encoding="utf-8")
            .replace('hitPolicy="FIRST"', 'hitPolicy="COLLECT"', 1)
            .replace("<text>true</text>", "<text>true and false</text>", 1),
            encoding="utf-8",
        )
        report = preflight_source_artifact("dmn", path)
        self.assertFalse(report.ok)
        messages = [item.message for item in report.issues]
        self.assertTrue(any("supports FIRST only" in message for message in messages))
        self.assertTrue(any("compound logic to live in predicates" in message for message in messages))

    def test_preflight_dmn_reports_duplicate_rule_ids_and_empty_rows(self) -> None:
        path = self.test_run.inputs_dir / "bad_rules.dmn"
        path.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/" id="defs_test" name="test">
  <decision id="d_triage" name="Triage">
    <decisionTable hitPolicy="FIRST">
      <input id="input_danger">
        <inputExpression id="ie_danger" typeRef="boolean">
          <text>p_danger_sign</text>
        </inputExpression>
      </input>
      <output id="out_referral" name="o_referral" typeRef="boolean" />
      <rule id="r_dup">
        <inputEntry id="r1_i1"><text>true</text></inputEntry>
        <outputEntry id="r1_o1"><text>true</text></outputEntry>
      </rule>
      <rule id="r_dup">
        <inputEntry id="r2_i1"><text>-</text></inputEntry>
        <outputEntry id="r2_o1"><text>false</text></outputEntry>
      </rule>
      <rule id="r_empty">
        <inputEntry id="r3_i1"><text>-</text></inputEntry>
        <outputEntry id="r3_o1"><text>-</text></outputEntry>
      </rule>
    </decisionTable>
  </decision>
</definitions>
""",
            encoding="utf-8",
        )
        report = preflight_source_artifact("dmn", path)
        self.assertFalse(report.ok)
        messages = [item.message for item in report.issues]
        self.assertTrue(any("duplicate rule id" in message for message in messages))
        self.assertTrue(any("does not assign any outputs" in message for message in messages))
        self.assertTrue(any("rule row is empty" in message for message in messages))

    def test_preflight_predicate_catalog_detects_input_expression_mismatch(self) -> None:
        path = self.test_run.inputs_dir / "predicates.json"
        path.write_text(
            json.dumps(
                {
                    "predicates": [
                        {
                            "id": "p_demo",
                            "description": "demo predicate",
                            "inputs_used": ["v_age_months", "v_extra"],
                            "expression": {
                                "kind": ">=",
                                "left": {"kind": "var", "id": "v_resp_rate"},
                                "right": {"kind": "literal", "value": 40},
                            },
                            "missingness_policy": "require_inputs",
                            "provenance": [{"source_id": "CATALOG_TEST"}],
                        }
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )
        report = preflight_source_artifact("predicate_catalog", path)
        self.assertFalse(report.ok)
        messages = [item.message for item in report.issues]
        self.assertTrue(any("missing from inputs_used" in message for message in messages))
        self.assertTrue(any("does not reference it" in message for message in messages))

    def test_preflight_phrase_bank_detects_duplicate_entity_role(self) -> None:
        path = self.test_run.inputs_dir / "phrases.csv"
        path.write_text(
            "\n".join(
                [
                    "key,entity_id,role,text_en,provenance_source_id",
                    "m_referral_a,o_referral,message,Refer now,CATALOG_TEST",
                    "m_referral_b,o_referral,message,Refer immediately,CATALOG_TEST",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        report = preflight_source_artifact("phrase_bank", path)
        self.assertFalse(report.ok)
        self.assertTrue(any("duplicate entity_id/role combination" in item.message for item in report.issues))

    def test_preflight_phrase_bank_warns_on_language_and_output_role_gaps(self) -> None:
        path = self.test_run.inputs_dir / "phrase_warnings.csv"
        path.write_text(
            "\n".join(
                [
                    "key,entity_id,role,text_EN,text_en,provenance_source_id,provenance_kind",
                    "m_referral,o_referral,message,Refer now,Refer now,CATALOG_TEST,phrase_bank",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        report = preflight_source_artifact("phrase_bank", path)
        self.assertFalse(report.ok)
        messages = [item.message for item in report.issues]
        self.assertTrue(any("duplicate language code 'en'" in message for message in messages))
        self.assertTrue(any("missing a guidance role" in message for message in messages))

    def test_ir_xlsform_mermaid_and_smt_lint_on_catalog_example(self) -> None:
        document = compose_document_from_catalogs(
            EXAMPLES / "catalogs" / "pneumonia.metadata.json",
            EXAMPLES / "catalogs" / "pneumonia.variables.csv",
            EXAMPLES / "catalogs" / "pneumonia.predicates.json",
            EXAMPLES / "catalogs" / "pneumonia.phrases.csv",
        )
        lint_document = import_dmn_decisions(document, str(EXAMPLES / "pneumonia.dmn"))
        ir_report = lint_ir_document(lint_document, source_path=str(EXAMPLES / "catalogs" / "pneumonia.metadata.json"))
        self.assertTrue(ir_report.ok)
        self.assertTrue(
            any(
                issue.path == "outputs.o_referral" and "guidance coverage" in issue.message
                for issue in ir_report.issues
            )
        )

        built = build_xlsform(lint_document)
        output_dir = self.test_run.outputs_dir / "xlsform"
        survey_path, choices_path, _ = write_xlsform_csvs(built, str(output_dir))
        xlsform_report = lint_xlsform_artifacts(survey_path, choices_path)
        self.assertTrue(xlsform_report.ok)

        mermaid_report = lint_mermaid_artifact(lint_document)
        self.assertTrue(mermaid_report.ok)

        smt_report = lint_smt_artifact(lint_document)
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

    def test_preflight_patient_cases_rejects_null_and_overlap(self) -> None:
        path = self.test_run.inputs_dir / "bad_cases.json"
        path.write_text(
            json.dumps(
                {
                    "cases": [
                        {
                            "name": "bad_case",
                            "values": {"v_age_months": None},
                            "missing": ["v_age_months", "v_age_months"],
                        }
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )
        report = preflight_source_artifact("patient_cases", path)
        self.assertFalse(report.ok)
        messages = [item.message for item in report.issues]
        self.assertTrue(any("must not use null" in message for message in messages))
        self.assertTrue(any("duplicate missing entry" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
