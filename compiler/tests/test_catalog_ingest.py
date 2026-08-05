from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.catalogs import CatalogLoadError, compose_document_from_catalogs
from chw_navigator.clinical_ir import ClinicalIRDocument
from chw_navigator.staged_lint import preflight_catalog_bundle
from chw_navigator.dmn import import_dmn_decisions
from chw_navigator.validator import validate_document
from chw_navigator.xlsform_backend import build_xlsform
from test_support import create_test_run, reset_suite_runs


EXAMPLES = ROOT / "examples"


class CatalogIngestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_suite_runs("catalog_ingest")

    def setUp(self) -> None:
        self.test_run = create_test_run(
            suite_name="catalog_ingest",
            test_name=self.id().split(".")[-1],
            purpose="Catalog ingest tests that synthesize standalone variable, predicate, phrase, and metadata inputs.",
            input_paths=(EXAMPLES / "pneumonia.dmn",),
        )
        self.metadata_path = self.test_run.inputs_dir / "metadata.json"
        self.variable_catalog_path = self.test_run.inputs_dir / "variables.csv"
        self.predicate_catalog_path = self.test_run.inputs_dir / "predicates.json"
        self.phrase_bank_path = self.test_run.inputs_dir / "phrases.csv"

        self.metadata_path.write_text(
            json.dumps(
                {
                    "ir_version": 1,
                    "guideline_id": "catalog_pneumonia",
                    "sources": [{"source_id": "CATALOG_TEST"}],
                }
            )
            + "\n",
            encoding="utf-8",
        )

        self.variable_catalog_path.write_text(
            "\n".join(
                [
                    "id,type,domain_min,domain_max,unit,allowed_missingness,multivalue,provenance_source_id,provenance_kind,provenance_location",
                    "v_age_months,int,0,120,months,false,false,CATALOG_TEST,variable_catalog,row:1",
                    "v_resp_rate,int,0,120,breaths_per_minute,false,false,CATALOG_TEST,variable_catalog,row:2",
                    "v_danger_sign,bool,,,,false,false,CATALOG_TEST,variable_catalog,row:3",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        self.predicate_catalog_path.write_text(
            json.dumps(
                {
                    "predicates": [
                        {
                            "id": "p_danger_sign",
                            "inputs_used": ["v_danger_sign"],
                            "expression": {"kind": "var", "id": "v_danger_sign"},
                            "missingness_policy": "require_inputs",
                            "description": "Danger sign present",
                            "provenance": [{"source_id": "CATALOG_TEST", "kind": "predicate_catalog", "location": "row:1"}],
                        },
                        {
                            "id": "p_fast_breathing",
                            "inputs_used": ["v_age_months", "v_resp_rate"],
                            "expression": {
                                "kind": "or",
                                "args": [
                                    {
                                        "kind": "and",
                                        "args": [
                                            {
                                                "kind": "<",
                                                "left": {"kind": "var", "id": "v_age_months"},
                                                "right": {"kind": "literal", "value": 12},
                                            },
                                            {
                                                "kind": ">=",
                                                "left": {"kind": "var", "id": "v_resp_rate"},
                                                "right": {"kind": "literal", "value": 50},
                                            },
                                        ],
                                    },
                                    {
                                        "kind": "and",
                                        "args": [
                                            {
                                                "kind": ">=",
                                                "left": {"kind": "var", "id": "v_age_months"},
                                                "right": {"kind": "literal", "value": 12},
                                            },
                                            {
                                                "kind": ">=",
                                                "left": {"kind": "var", "id": "v_resp_rate"},
                                                "right": {"kind": "literal", "value": 40},
                                            },
                                        ],
                                    },
                                ],
                            },
                            "missingness_policy": "require_inputs",
                            "description": "Fast breathing present",
                            "provenance": [{"source_id": "CATALOG_TEST", "kind": "predicate_catalog", "location": "row:2"}],
                        },
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )

        self.phrase_bank_path.write_text(
            "\n".join(
                [
                    "key,entity_id,role,text_en,text_fr,provenance_source_id,provenance_kind,provenance_location",
                    "m_v_age_months,v_age_months,label,Child age (months),Age de l'enfant (mois),CATALOG_TEST,phrase_bank,row:1",
                    "m_v_resp_rate,v_resp_rate,label,Respiratory rate,Frequence respiratoire,CATALOG_TEST,phrase_bank,row:2",
                    "m_o_referral,o_referral,message,Refer urgently to facility.,Referer en urgence a l'etablissement.,CATALOG_TEST,phrase_bank,row:3",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    def test_compose_ir_from_catalogs_and_import_dmn(self) -> None:
        document = compose_document_from_catalogs(
            self.metadata_path,
            self.variable_catalog_path,
            self.predicate_catalog_path,
            self.phrase_bank_path,
        )
        self.assertEqual([], validate_document(document))
        imported = import_dmn_decisions(document, str(EXAMPLES / "pneumonia.dmn"))
        self.assertIn("o_referral", imported.outputs)
        self.assertEqual([], validate_document(imported))

        built = build_xlsform(imported)
        age_row = next(row for row in built.workbook.survey if row.name == "v_age_months")
        message_row = next(row for row in built.workbook.survey if row.name == "note_o_referral")
        self.assertEqual("Child age (months)", age_row.label)
        self.assertEqual("Refer urgently to facility.", message_row.label)

    def test_rejects_invalid_predicate_expression_json(self) -> None:
        bad_path = self.test_run.inputs_dir / "bad_predicates.csv"
        bad_path.write_text(
            "\n".join(
                [
                    "id,inputs_used,expression_json,missingness_policy,provenance_source_id",
                    'p_bad,"v_age_months","{bad json}",require_inputs,CATALOG_TEST',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(CatalogLoadError):
            compose_document_from_catalogs(
                self.metadata_path,
                self.variable_catalog_path,
                bad_path,
                self.phrase_bank_path,
            )

    def test_supports_json_variable_and_phrase_catalogs(self) -> None:
        variable_json = self.test_run.inputs_dir / "variables.json"
        phrase_json = self.test_run.inputs_dir / "phrases.json"
        predicate_csv = self.test_run.inputs_dir / "predicates.csv"

        variable_json.write_text(
            json.dumps(
                {
                    "variables": [
                        {
                            "id": "v_has_fever",
                            "type": "bool",
                            "allowed_missingness": False,
                            "multivalue": False,
                            "provenance": [{"source_id": "CATALOG_TEST"}],
                        }
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )
        predicate_csv.write_text(
            "\n".join(
                [
                    "id,inputs_used,expression_json,missingness_policy,description,provenance_source_id",
                    'p_has_fever,"[""v_has_fever""]","{""kind"": ""var"", ""id"": ""v_has_fever""}",require_inputs,Has fever,CATALOG_TEST',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        phrase_json.write_text(
            json.dumps(
                {
                    "phrases": [
                        {
                            "key": "m_v_has_fever",
                            "entity_id": "v_has_fever",
                            "role": "label",
                            "texts": {"en": "Fever present"},
                            "provenance": [{"source_id": "CATALOG_TEST"}],
                        }
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )

        document = compose_document_from_catalogs(
            self.metadata_path,
            variable_json,
            predicate_csv,
            phrase_json,
        )
        self.assertEqual([], validate_document(document))
        self.assertIsInstance(document, ClinicalIRDocument)

    def test_accepts_ehr_history_suffix_variables(self) -> None:
        variable_json = self.test_run.inputs_dir / "variables_ehr.json"
        predicate_json = self.test_run.inputs_dir / "predicates_ehr.json"
        phrase_json = self.test_run.inputs_dir / "phrases_ehr.json"

        variable_json.write_text(
            json.dumps(
                {
                    "variables": [
                        {
                            "id": "v_weight_kg_h",
                            "type": "decimal",
                            "allowed_missingness": True,
                            "multivalue": False,
                            "provenance": [{"source_id": "CATALOG_TEST", "kind": "ehr_extract"}],
                        },
                        {
                            "id": "st_prev_referral_h",
                            "type": "bool",
                            "allowed_missingness": True,
                            "multivalue": False,
                            "provenance": [{"source_id": "CATALOG_TEST", "kind": "ehr_extract"}],
                        },
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )
        predicate_json.write_text(
            json.dumps(
                {
                    "predicates": [
                        {
                            "id": "p_has_prior_referral",
                            "inputs_used": ["st_prev_referral_h"],
                            "expression": {"kind": "var", "id": "st_prev_referral_h"},
                            "missingness_policy": "require_inputs",
                            "description": "Prior referral recorded in EHR history",
                            "provenance": [{"source_id": "CATALOG_TEST", "kind": "predicate_catalog"}],
                        }
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )
        phrase_json.write_text(
            json.dumps(
                {
                    "phrases": [
                        {
                            "key": "m_v_weight_kg_h",
                            "entity_id": "v_weight_kg_h",
                            "role": "label",
                            "texts": {"en": "Historical weight (kg)"},
                            "provenance": [{"source_id": "CATALOG_TEST", "kind": "phrase_bank"}],
                        }
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )

        document = compose_document_from_catalogs(
            self.metadata_path,
            variable_json,
            predicate_json,
            phrase_json,
        )
        self.assertEqual([], validate_document(document))
        self.assertIn("v_weight_kg_h", document.variables)
        self.assertIn("st_prev_referral_h", document.variables)

    def test_crossfile_preflight_reports_output_guidance_gap_after_dmn_import(self) -> None:
        report = preflight_catalog_bundle(
            metadata_path=EXAMPLES / "catalogs" / "pneumonia.metadata.json",
            variable_catalog_path=EXAMPLES / "catalogs" / "pneumonia.variables.csv",
            predicate_catalog_path=EXAMPLES / "catalogs" / "pneumonia.predicates.json",
            phrase_bank_path=EXAMPLES / "catalogs" / "pneumonia.phrases.csv",
            dmn_path=EXAMPLES / "pneumonia.dmn",
        )
        self.assertTrue(report.ok)
        self.assertTrue(
            any(
                issue.path == "outputs.o_referral" and "guidance coverage" in issue.message
                for issue in report.issues
            )
        )

    def test_crossfile_preflight_warns_on_phrase_entity_missing_from_compiled_ir(self) -> None:
        phrase_path = self.test_run.inputs_dir / "phrases_orphan.csv"
        phrase_path.write_text(
            "\n".join(
                [
                    "key,entity_id,role,text_en,provenance_source_id,provenance_kind,provenance_location",
                    "m_v_age_months,v_age_months,label,Child age (months),CATALOG_TEST,phrase_bank,row:1",
                    "m_v_resp_rate,v_resp_rate,label,Respiratory rate,CATALOG_TEST,phrase_bank,row:2",
                    "m_o_referral,o_referral,message,Refer urgently to facility.,CATALOG_TEST,phrase_bank,row:3",
                    "m_orphan,o_missing,message,Orphan text,CATALOG_TEST,phrase_bank,row:4",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        report = preflight_catalog_bundle(
            metadata_path=self.metadata_path,
            variable_catalog_path=self.variable_catalog_path,
            predicate_catalog_path=self.predicate_catalog_path,
            phrase_bank_path=phrase_path,
            dmn_path=EXAMPLES / "pneumonia.dmn",
        )
        self.assertTrue(report.ok)
        self.assertTrue(
            any(
                "does not match any variable, predicate, action, output, or decision" in issue.message
                for issue in report.issues
            )
        )


if __name__ == "__main__":
    unittest.main()
