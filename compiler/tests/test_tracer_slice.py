from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
EXAMPLES = ROOT / "examples" / "tracer"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.clinical_ir import ClinicalIRDocument
from chw_navigator.diagnostics import DiagnosticCode
from chw_navigator.registry_set import load_registry_set, resolve_capability
from chw_navigator.special_functions import SPECIAL_FUNCTION_STATUSES, calculate_gestational_age_naegele
from chw_navigator.tracer import TracerBuildError, build_tracer, validate_capability_invocation


class TracerSliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        root = Path(cls.temporary.name)
        cls.build = build_tracer(root / "bundle", evidence_manifest=root / "evidence.json")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_hand_derived_reference_vectors_execute(self) -> None:
        payload = json.loads((EXAMPLES / "reference-vectors.json").read_text(encoding="utf-8"))
        self.assertIn("Hand-derived", payload["derivation"])
        self.assertEqual(
            {"day-zero", "month-boundary", "leap-year", "exact-280-day", "domain-edge", "past-domain", "reference-before-lmp"},
            {item["name"] for item in payload["vectors"]},
        )
        for vector in payload["vectors"]:
            result = calculate_gestational_age_naegele(**vector["input"])
            self.assertEqual(vector["status"], result.status, vector["name"])
            self.assertEqual(vector.get("technical"), result.technical, vector["name"])

    def test_form_binds_registered_local_read_and_technical_outputs(self) -> None:
        xform = self.build.adapter.form_xform_path.read_text(encoding="utf-8")
        self.assertIn("most_recent_lmp_date", xform)
        self.assertIn("'missing'", xform)
        self.assertIn("'stale'", xform)
        self.assertIn("cht:extension-lib('gestational-age-from-lmp.js'", xform)
        self.assertIn('nodeset="/data/technical/ga_weeks" type="int"', xform)
        self.assertIn('nodeset="/data/technical/ga_days_remainder" type="int"', xform)
        self.assertIn('nodeset="/data/technical/edd" type="date"', xform)

    def test_only_referenced_extension_is_emitted(self) -> None:
        extension_paths = [path.name for path in (self.build.output_dir / "extension-libs").iterdir()]
        self.assertEqual(["gestational-age-from-lmp.js"], extension_paths)
        all_paths = " ".join(path.as_posix() for path in self.build.output_dir.rglob("*"))
        self.assertNotIn("weight", all_paths.lower())

    def test_all_statuses_are_explicit_and_removing_one_fails(self) -> None:
        payload = json.loads((EXAMPLES / "tracer.ir.json").read_text(encoding="utf-8"))
        document = ClinicalIRDocument.from_dict(payload)
        capability = resolve_capability(load_registry_set(EXAMPLES / "registry-set.json"), "technical.gestational-age.naegele")
        validate_capability_invocation(document, capability)
        rules = payload["decisions"]["d_followup_endpoint"]["rules"]
        payload["decisions"]["d_followup_endpoint"]["rules"] = [item for item in rules if item["id"] != "r_execution"]
        with self.assertRaises(TracerBuildError) as raised:
            validate_capability_invocation(ClinicalIRDocument.from_dict(payload), capability)
        self.assertEqual(DiagnosticCode.STATUS_COVERAGE_INCOMPLETE, raised.exception.diagnostics[0].code)
        self.assertEqual(8, len(SPECIAL_FUNCTION_STATUSES))

    def test_unresolved_ir_reference_has_stable_code(self) -> None:
        registry = load_registry_set(EXAMPLES / "registry-set.json")
        with self.assertRaises(Exception) as raised:
            resolve_capability(registry, "technical.not-registered")
        self.assertEqual(DiagnosticCode.CAPABILITY_REFERENCE_UNRESOLVED, raised.exception.diagnostics[0].code)

    def test_invalid_invocation_contract_has_stable_code(self) -> None:
        payload = json.loads((EXAMPLES / "tracer.ir.json").read_text(encoding="utf-8"))
        payload["actions"]["a_invoke_naegele"]["arguments"] = {
            "reference_date": "st_reference_date",
            "lmp_date": "h_lmp_date",
        }
        document = ClinicalIRDocument.from_dict(payload)
        capability = resolve_capability(
            load_registry_set(EXAMPLES / "registry-set.json"),
            "technical.gestational-age.naegele",
        )
        with self.assertRaises(TracerBuildError) as raised:
            validate_capability_invocation(document, capability)
        self.assertEqual(DiagnosticCode.CAPABILITY_INVOCATION_INVALID, raised.exception.diagnostics[0].code)

    def test_two_clean_builds_have_identical_deterministic_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = build_tracer(root / "a", evidence_manifest=root / "a.json")
            second = build_tracer(root / "b", evidence_manifest=root / "b.json")
        self.assertEqual(first.deterministic, second.deterministic)

    def test_manifest_preserves_evidence_ceiling(self) -> None:
        payload = json.loads(self.build.evidence_manifest.read_text(encoding="utf-8"))
        self.assertEqual("E2", payload["evidence_level"])
        self.assertFalse(payload["deployment_ready"])
        self.assertEqual("pass", payload["deterministic"]["harness"]["status"])
        self.assertEqual("pass", payload["deterministic"]["oracle"]["status"])
        self.assertEqual("not_run", payload["environment"]["exact_cht_sandbox"]["status"])


if __name__ == "__main__":
    unittest.main()
