from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from defusedxml import ElementTree


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
EXAMPLES = ROOT / "examples"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.cht_backend import build_cht_lowering_plan, write_cht_adapter_stub
from chw_navigator.cht_special_functions import (
    UnreviewedCHTVersionError,
    gestational_age_extension_source,
    lower_reviewed_special_functions,
    reviewed_cht_profile,
    reviewed_cht_versions,
    write_cht_special_function_bundle,
)
from chw_navigator.clinical_ir import ClinicalIRDocument
from chw_navigator.diagnostics import DiagnosticCode
from chw_navigator.special_functions import (
    SPECIAL_FUNCTION_STATUSES,
    calculate_gestational_age_from_lmp,
    validate_extension_return,
    validate_status_coverage,
    verify_registry_digests,
)


VECTORS = EXAMPLES / "special_functions" / "gestational-age-vectors.json"
REGISTRY = ROOT / "contracts" / "special-function-registry.json"


class SpecialFunctionTests(unittest.TestCase):
    def test_gestational_age_vectors_match_registered_python_function(self) -> None:
        document = json.loads(VECTORS.read_text(encoding="utf-8"))
        for vector in document["vectors"]:
            result = calculate_gestational_age_from_lmp(**vector["input"])
            self.assertEqual(vector["expected_status"], result.status, vector["name"])
            if "expected_technical" in vector:
                self.assertEqual(vector["expected_technical"], result.technical, vector["name"])
                self.assertEqual("half-even-1", result.provenance["rounding"])

    def test_registry_digests_are_enforced(self) -> None:
        source = gestational_age_extension_source()
        self.assertEqual(
            [],
            verify_registry_digests(REGISTRY, implementation_source=source, vector_path=VECTORS),
        )
        implementation = verify_registry_digests(
            REGISTRY,
            implementation_source=source + "\n// drift",
            vector_path=VECTORS,
        )
        self.assertEqual(DiagnosticCode.IMPLEMENTATION_DIGEST_MISMATCH, implementation[0].code)
        with tempfile.TemporaryDirectory() as temporary:
            changed_vectors = Path(temporary) / "vectors.json"
            changed_vectors.write_bytes(VECTORS.read_bytes() + b"\n")
            vectors = verify_registry_digests(
                REGISTRY,
                implementation_source=source,
                vector_path=changed_vectors,
            )
        self.assertEqual(DiagnosticCode.VECTOR_DIGEST_MISMATCH, vectors[0].code)

    def test_closed_status_set_and_extension_envelope_fail_closed(self) -> None:
        form = next(
            artifact.content
            for artifact in lower_reviewed_special_functions("4.22.0").files
            if artifact.path.endswith("technical_gestational_age.xml")
        )
        self.assertEqual([], validate_status_coverage(form))
        missing = validate_status_coverage(form.replace("execution_failure", "removed_status"))
        self.assertEqual(DiagnosticCode.STATUS_COVERAGE_INCOMPLETE, missing[0].code)
        self.assertEqual([], validate_extension_return({"t": "str", "v": "ok|1,2026-10-08"}))
        invalid = validate_extension_return({"t": "num", "v": -99})
        self.assertEqual(DiagnosticCode.INVALID_EXTENSION_RETURN, invalid[0].code)
        self.assertEqual(8, len(SPECIAL_FUNCTION_STATUSES))

    def test_profiles_separate_4_22_and_5_2_expression_capabilities(self) -> None:
        self.assertEqual(("4.22.0", "5.2.0"), reviewed_cht_versions())
        self.assertFalse(reviewed_cht_profile("4.22.0").extension_lib_expression)
        self.assertTrue(reviewed_cht_profile("5.2.0").extension_lib_expression)
        with self.assertRaises(UnreviewedCHTVersionError) as raised:
            reviewed_cht_profile("5.1.3")
        self.assertEqual(DiagnosticCode.UNREVIEWED_CHT_VERSION, raised.exception.code)

    def test_both_profiles_emit_valid_forms_native_wfa_and_extension_lmp(self) -> None:
        bundles = [lower_reviewed_special_functions(version) for version in reviewed_cht_versions()]
        contents = [{artifact.path: artifact.content for artifact in bundle.files} for bundle in bundles]
        self.assertEqual(contents[0], contents[1])
        for bundle in bundles:
            warning = next(item for item in bundle.diagnostics if item.severity == "warning")
            self.assertEqual(DiagnosticCode.NATIVE_REFERENCE_DATA_UNVERIFIED, warning.code)
            self.assertEqual([], [item for item in bundle.diagnostics if item.severity == "error"])
            for artifact in bundle.files:
                if artifact.path.endswith(".xml"):
                    ElementTree.fromstring(artifact.content)
            self.assertIn(
                "z-score(&apos;weight-for-age&apos;",
                contents[0]["forms/app/technical_wfa_z_score.xml"],
            )
            self.assertNotIn("weight", " ".join(path for path in contents[0] if path.startswith("extension-libs/")))
            gestational = contents[0]["forms/app/technical_gestational_age.xml"]
            self.assertEqual(1, gestational.count("&apos;compute&apos;"))
            self.assertIn("cht:extension-lib", gestational)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the generated CHT module execution check")
    def test_generated_commonjs_module_executes_with_real_cht_envelopes(self) -> None:
        bundle = lower_reviewed_special_functions("4.22.0")
        with tempfile.TemporaryDirectory() as temporary:
            paths = write_cht_special_function_bundle(bundle, temporary)
            module_path = Path(temporary) / "extension-libs" / "gestational-age-from-lmp.js"
            self.assertIn(module_path, paths)
            script = """
const extension = require(process.argv[1]);
const envelope = value => ({ t: 'arr', v: [{ textContent: value }] });
const result = extension({ t: 'str', v: 'compute' }, envelope('2026-01-01'), envelope('2026-01-08'));
process.stdout.write(JSON.stringify(result));
"""
            completed = subprocess.run(
                [shutil.which("node"), "-e", script, str(module_path)],
                check=True,
                capture_output=True,
                text=True,
            )
        self.assertEqual({"t": "str", "v": "ok|1,2026-10-08"}, json.loads(completed.stdout))

    def test_writer_is_non_clobbering_and_is_consumed_by_existing_cht_plan(self) -> None:
        document = ClinicalIRDocument.from_dict(
            json.loads((EXAMPLES / "pneumonia.ir.json").read_text(encoding="utf-8"))
        )
        plan = build_cht_lowering_plan(document, special_function_target_cht_version="5.2.0")
        self.assertIsNotNone(plan.special_function_bundle)
        with tempfile.TemporaryDirectory() as temporary:
            artifacts = write_cht_adapter_stub(plan, temporary)
            expected = Path(temporary) / "extension-libs" / "gestational-age-from-lmp.js"
            self.assertTrue(expected.exists())
            self.assertIn(expected.resolve(), artifacts.special_function_paths)
            self.assertEqual((), write_cht_special_function_bundle(plan.special_function_bundle, temporary))
            expected.write_text("divergent", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                write_cht_special_function_bundle(plan.special_function_bundle, temporary)


if __name__ == "__main__":
    unittest.main()
