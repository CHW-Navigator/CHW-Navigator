from __future__ import annotations

import json
import unittest
from pathlib import Path

from chw_navigator.bundles import create_bundle
from chw_navigator.clinical_ir import ClinicalIRDocument
from test_support import create_test_run, reset_suite_runs


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = PROJECT_ROOT / "examples"


class BundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_suite_runs("bundles")

    def setUp(self) -> None:
        self.test_run = create_test_run(
            suite_name="bundles",
            test_name=self.id().split(".")[-1],
            purpose="Bundle creation tests that verify one-run-per-folder audit packaging for DMN compiles.",
            input_paths=(EXAMPLES_DIR / "pneumonia.ir.json", EXAMPLES_DIR / "pneumonia.dmn", EXAMPLES_DIR / "pneumonia.cases.json"),
        )
        self.artifact_root = self.test_run.scratch_dir / "bundle_runs"
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    def test_create_bundle_writes_expected_structure_and_metadata(self) -> None:
        document = self._load_document(EXAMPLES_DIR / "pneumonia.ir.json")

        built = create_bundle(
            base_document=document,
            base_ir_path=EXAMPLES_DIR / "pneumonia.ir.json",
            dmn_path=EXAMPLES_DIR / "pneumonia.dmn",
            patient_cases_path=EXAMPLES_DIR / "pneumonia.cases.json",
            bundle_root=self.artifact_root,
            source_label="pneumonia-demo",
        )

        self.assertTrue(built.bundle_dir.exists())
        self.assertTrue((built.bundle_dir / "inputs" / "base.ir.json").exists())
        self.assertTrue((built.bundle_dir / "inputs" / "source.dmn").exists())
        self.assertTrue((built.bundle_dir / "inputs" / "explicit.cases.json").exists())
        self.assertTrue((built.bundle_dir / "inputs" / "lint" / "base.ir.lint.json").exists())
        self.assertTrue((built.bundle_dir / "inputs" / "lint" / "source.dmn.lint.json").exists())
        self.assertTrue((built.bundle_dir / "inputs" / "lint" / "explicit.cases.lint.json").exists())
        self.assertTrue((built.bundle_dir / "outputs" / "merged.ir.json").exists())
        self.assertTrue((built.bundle_dir / "outputs" / "lint" / "merged.ir.lint.json").exists())
        self.assertTrue((built.bundle_dir / "outputs" / "xlsform" / "survey.csv").exists())
        self.assertTrue((built.bundle_dir / "outputs" / "xlsform" / "choices.csv").exists())
        self.assertTrue((built.bundle_dir / "outputs" / "xlsform" / "lint.json").exists())
        self.assertTrue((built.bundle_dir / "outputs" / "mermaid" / "pneumonia-demo.mmd").exists())
        self.assertTrue((built.bundle_dir / "outputs" / "mermaid" / "lint.json").exists())
        self.assertTrue((built.bundle_dir / "outputs" / "z3" / "pneumonia-demo.smt2").exists())
        self.assertTrue((built.bundle_dir / "outputs" / "z3" / "smt2.lint.json").exists())
        self.assertTrue((built.bundle_dir / "tests" / "good" / "explicit.compare.json").exists())
        self.assertTrue((built.bundle_dir / "tests" / "good" / "z3-derived.compare.json").exists())
        self.assertTrue((built.bundle_dir / "mutations" / "manifest.json").exists())
        self.assertTrue(built.hash_manifest_path.exists())

        metadata = json.loads(built.metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["source"]["source_label"], "pneumonia-demo")
        self.assertEqual(metadata["compiler"]["package"], "chw-navigator")
        self.assertEqual(metadata["copied_inputs"]["dmn"], "inputs/source.dmn")
        self.assertEqual(metadata["lint_reports"]["dmn"], "inputs/lint/source.dmn.lint.json")
        self.assertEqual(metadata["lint_reports"]["merged_ir"], "outputs/lint/merged.ir.lint.json")
        self.assertEqual(metadata["outputs"]["merged_ir"], "outputs/merged.ir.json")
        self.assertEqual(metadata["tests"]["explicit_compare"], "tests/good/explicit.compare.json")
        self.assertEqual(metadata["artifact_hash_manifest"], "artifact_hashes.json")

        hash_manifest = json.loads(built.hash_manifest_path.read_text(encoding="utf-8"))
        self.assertEqual("sha256", hash_manifest["algorithm"])
        self.assertTrue(hash_manifest["files"])
        hashed_paths = {entry["path"] for entry in hash_manifest["files"]}
        self.assertIn("inputs/source.dmn", hashed_paths)
        self.assertIn("inputs/lint/source.dmn.lint.json", hashed_paths)
        self.assertIn("outputs/merged.ir.json", hashed_paths)
        self.assertIn("outputs/xlsform/lint.json", hashed_paths)
        self.assertIn("outputs/mermaid/lint.json", hashed_paths)
        self.assertIn("outputs/z3/smt2.lint.json", hashed_paths)
        self.assertIn("metadata.json", hashed_paths)
        self.assertIn("README.md", hashed_paths)

        explicit_log = json.loads((built.bundle_dir / "tests" / "good" / "explicit.compare.json").read_text(encoding="utf-8"))
        self.assertEqual("comparison_report", explicit_log["log_type"])
        self.assertEqual(1, explicit_log["contract_version"])
        self.assertTrue(explicit_log["results"])
        self.assertIn("mismatches", explicit_log["results"][0])

        z3_log = json.loads((built.bundle_dir / "outputs" / "z3" / "z3-checks.json").read_text(encoding="utf-8"))
        self.assertEqual("z3_checks", z3_log["log_type"])
        self.assertEqual(1, z3_log["contract_version"])
        self.assertTrue(z3_log["results"])

    def test_create_bundle_never_overwrites_previous_bundle(self) -> None:
        document = self._load_document(EXAMPLES_DIR / "pneumonia.ir.json")

        first = create_bundle(
            base_document=document,
            base_ir_path=EXAMPLES_DIR / "pneumonia.ir.json",
            dmn_path=EXAMPLES_DIR / "pneumonia.dmn",
            bundle_root=self.artifact_root,
        )
        second = create_bundle(
            base_document=document,
            base_ir_path=EXAMPLES_DIR / "pneumonia.ir.json",
            dmn_path=EXAMPLES_DIR / "pneumonia.dmn",
            bundle_root=self.artifact_root,
        )

        self.assertNotEqual(first.bundle_dir, second.bundle_dir)
        self.assertTrue(first.bundle_dir.exists())
        self.assertTrue(second.bundle_dir.exists())

    @staticmethod
    def _load_document(path: Path) -> ClinicalIRDocument:
        return ClinicalIRDocument.from_dict(json.loads(path.read_text(encoding="utf-8")))
