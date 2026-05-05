from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from chw_navigator.bundles import create_bundle
from chw_navigator.clinical_ir import ClinicalIRDocument


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = PROJECT_ROOT / "examples"
ARTIFACT_ROOT = PROJECT_ROOT / "generated" / "test_artifacts" / "bundle_tests"


class BundleTests(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(ARTIFACT_ROOT, ignore_errors=True)
        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(ARTIFACT_ROOT, ignore_errors=True)

    def test_create_bundle_writes_expected_structure_and_metadata(self) -> None:
        document = self._load_document(EXAMPLES_DIR / "pneumonia.ir.json")

        built = create_bundle(
            base_document=document,
            base_ir_path=EXAMPLES_DIR / "pneumonia.ir.json",
            dmn_path=EXAMPLES_DIR / "pneumonia.dmn",
            patient_cases_path=EXAMPLES_DIR / "pneumonia.cases.json",
            bundle_root=ARTIFACT_ROOT,
            source_label="pneumonia-demo",
        )

        self.assertTrue(built.bundle_dir.exists())
        self.assertTrue((built.bundle_dir / "inputs" / "base.ir.json").exists())
        self.assertTrue((built.bundle_dir / "inputs" / "source.dmn").exists())
        self.assertTrue((built.bundle_dir / "inputs" / "explicit.cases.json").exists())
        self.assertTrue((built.bundle_dir / "outputs" / "merged.ir.json").exists())
        self.assertTrue((built.bundle_dir / "outputs" / "xlsform" / "survey.csv").exists())
        self.assertTrue((built.bundle_dir / "outputs" / "xlsform" / "choices.csv").exists())
        self.assertTrue((built.bundle_dir / "outputs" / "mermaid" / "pneumonia-demo.mmd").exists())
        self.assertTrue((built.bundle_dir / "outputs" / "z3" / "pneumonia-demo.smt2").exists())
        self.assertTrue((built.bundle_dir / "tests" / "good" / "explicit.compare.json").exists())
        self.assertTrue((built.bundle_dir / "tests" / "good" / "z3-derived.compare.json").exists())
        self.assertTrue((built.bundle_dir / "mutations" / "manifest.json").exists())

        metadata = json.loads(built.metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["source"]["source_label"], "pneumonia-demo")
        self.assertEqual(metadata["compiler"]["package"], "chw-navigator")
        self.assertEqual(metadata["copied_inputs"]["dmn"], "inputs/source.dmn")
        self.assertEqual(metadata["outputs"]["merged_ir"], "outputs/merged.ir.json")
        self.assertEqual(metadata["tests"]["explicit_compare"], "tests/good/explicit.compare.json")

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
            bundle_root=ARTIFACT_ROOT,
        )
        second = create_bundle(
            base_document=document,
            base_ir_path=EXAMPLES_DIR / "pneumonia.ir.json",
            dmn_path=EXAMPLES_DIR / "pneumonia.dmn",
            bundle_root=ARTIFACT_ROOT,
        )

        self.assertNotEqual(first.bundle_dir, second.bundle_dir)
        self.assertTrue(first.bundle_dir.exists())
        self.assertTrue(second.bundle_dir.exists())

    @staticmethod
    def _load_document(path: Path) -> ClinicalIRDocument:
        return ClinicalIRDocument.from_dict(json.loads(path.read_text(encoding="utf-8")))
