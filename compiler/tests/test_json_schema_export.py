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
from chw_navigator.json_schema_export import build_json_schema, write_json_schemas
from test_support import create_test_run, reset_suite_runs


class JsonSchemaExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_suite_runs("json_schema_export")

    def setUp(self) -> None:
        self.test_run = create_test_run(
            suite_name="json_schema_export",
            test_name=self.id().split(".")[-1],
            purpose="Machine-checked JSON Schema export tests for supported JSON artifact families.",
        )

    def test_build_json_schema_for_catalog_payloads(self) -> None:
        schema = build_json_schema("predicate_catalog_json")
        self.assertEqual("object", schema["type"])
        self.assertIn("predicates", schema["properties"])
        item_ref = schema["properties"]["predicates"]["items"]["$ref"]
        self.assertTrue(item_ref.endswith("PredicateModel"))

    def test_write_json_schemas_writes_expected_files(self) -> None:
        output_dir = self.test_run.outputs_dir / "schemas"
        written = write_json_schemas(output_dir)
        self.assertIn("clinical_ir", written)
        self.assertIn("patient_case_suite", written)
        self.assertTrue(all(path.exists() for path in written.values()))
        schema_payload = json.loads((output_dir / "variable_catalog_json.schema.json").read_text(encoding="utf-8"))
        self.assertIn("variables", schema_payload["properties"])

    def test_write_json_schemas_cli(self) -> None:
        output_dir = self.test_run.outputs_dir / "cli_schemas"
        exit_code = cli_main(["write-json-schemas", str(output_dir)])
        self.assertEqual(0, exit_code)
        self.assertTrue((output_dir / "clinical_ir.schema.json").exists())
        self.assertTrue((output_dir / "phrase_bank_json.schema.json").exists())


if __name__ == "__main__":
    unittest.main()
