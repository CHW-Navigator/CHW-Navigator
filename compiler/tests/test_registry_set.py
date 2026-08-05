from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FIXTURES = ROOT / "contracts" / "examples" / "tracer"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.diagnostics import DiagnosticCode
from chw_navigator.registry_set import (
    Capability,
    RegistrySetError,
    compute_registry_set_digest,
    load_registry_set,
    parse_registry_set,
    resolve_capability,
    seal_registry_set,
)


CAPABILITY_ID = "technical.gestational-age.naegele"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _apply_case(payload: dict, case: dict) -> dict:
    changed = copy.deepcopy(payload)
    parent = changed
    for segment in case["path"][:-1]:
        parent = parent[segment]
    leaf = case["path"][-1]
    if case["operation"] == "delete":
        del parent[leaf]
    else:
        parent[leaf] = case["value"]
    return seal_registry_set(changed) if case["reseal"] else changed


class RegistrySetTests(unittest.TestCase):
    def test_positive_fixture_is_locked_and_resolves(self) -> None:
        document = load_registry_set(FIXTURES / "valid-registry-set.json")
        self.assertEqual(document.content_digest, compute_registry_set_digest(document))
        capability = resolve_capability(
            document,
            CAPABILITY_ID,
            required_target_features=("registered_local_read", "recorded_at_freshness"),
        )
        self.assertEqual("tracer_enabled", capability.evidence_status)
        self.assertEqual(["lmp_date", "reference_date"], [item.name for item in capability.inputs])

    def test_capability_surface_is_exactly_the_ws1_contract(self) -> None:
        expected = {
            "id", "version", "content_digest", "family", "operation", "inputs", "outputs",
            "status_set", "supported_domain", "rounding", "determinism", "side_effects",
            "implementation_binding", "evidence_status", "supported_target_profiles", "subject_scope",
        }
        self.assertEqual(
            expected,
            set(Capability.model_fields),
        )
        schema = json.loads((ROOT / "contracts" / "capability-registry.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(expected, set(schema["$defs"]["capability"]["required"]))
        self.assertEqual(expected, set(schema["$defs"]["capability"]["properties"]))
        self.assertNotIn("approval", " ".join(sorted(expected)))

    def test_mutating_locked_sources_changes_the_recomputed_set_digest(self) -> None:
        base = _fixture("valid-registry-set.json")
        original = compute_registry_set_digest(base)
        mutations = []
        changed_capability = copy.deepcopy(base)
        changed_capability["capability_registry"]["capabilities"][0]["operation"] = "changed"
        mutations.append(changed_capability)
        changed_target = copy.deepcopy(base)
        changed_target["target_profile"]["form_engine"]["version"] = "4.11.1"
        mutations.append(changed_target)
        changed_input_order = copy.deepcopy(base)
        changed_input_order["capability_registry"]["capabilities"][0]["inputs"].reverse()
        mutations.append(changed_input_order)
        for mutation in mutations:
            self.assertNotEqual(original, compute_registry_set_digest(mutation))
            self.assertEqual(compute_registry_set_digest(mutation), parse_registry_set(seal_registry_set(mutation)).content_digest)

    def test_set_digest_is_derived_only_from_named_member_digests(self) -> None:
        payload = _fixture("valid-registry-set.json")
        members = {
            "capability_registry": payload["capability_registry"]["content_digest"],
            "target_profile": payload["target_profile"]["content_digest"],
        }
        canonical = json.dumps(members, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.assertEqual(f"sha256:{hashlib.sha256(canonical).hexdigest()}", payload["content_digest"])

    def test_each_negative_fixture_emits_its_stable_code(self) -> None:
        base = _fixture("valid-registry-set.json")
        cases = _fixture("negative-cases.json")["cases"]
        for case in cases:
            with self.subTest(case=case["name"]):
                changed = _apply_case(base, case)
                with self.assertRaises(RegistrySetError) as raised:
                    document = parse_registry_set(changed)
                    if case["stage"].startswith("resolve"):
                        features = ("recorded_at_freshness",) if case["stage"] == "resolve_with_recorded_at" else ()
                        resolve_capability(document, CAPABILITY_ID, required_target_features=features)
                self.assertIn(case["expected_code"], {str(item.code) for item in raised.exception.diagnostics})

    def test_diagnostic_categories_are_distinct_and_declared(self) -> None:
        self.assertNotEqual(DiagnosticCode.REGISTRY_UNIT_MISSING, DiagnosticCode.REGISTRY_VERSION_MISSING)
        self.assertNotEqual(DiagnosticCode.REGISTRY_VERSION_MISSING, DiagnosticCode.REGISTRY_DIGEST_MISSING)
        self.assertNotEqual(DiagnosticCode.REGISTRY_DIGEST_MISSING, DiagnosticCode.SUBJECT_SCOPE_MISSING)
        self.assertNotEqual(DiagnosticCode.SUBJECT_SCOPE_MISSING, DiagnosticCode.TARGET_FEATURE_MISSING)
        self.assertEqual("CHWN-REG-000", DiagnosticCode.REGISTRY_SCHEMA_INVALID)
        self.assertEqual("CHWN-REG-004", DiagnosticCode.REGISTRY_DIGEST_MISMATCH)
        self.assertEqual("CHWN-REG-005", DiagnosticCode.REGISTRY_CANDIDATE_UNRESOLVED)
        self.assertEqual("CHWN-REG-006", DiagnosticCode.REGISTRY_UNKNOWN_FIELD)
        self.assertEqual("CHWN-RESOLVE-001", DiagnosticCode.CAPABILITY_REFERENCE_UNRESOLVED)

    def test_unregistered_capability_has_a_resolution_diagnostic(self) -> None:
        document = load_registry_set(FIXTURES / "valid-registry-set.json")
        with self.assertRaises(RegistrySetError) as raised:
            resolve_capability(document, "technical.missing")
        self.assertEqual(DiagnosticCode.CAPABILITY_REFERENCE_UNRESOLVED, raised.exception.diagnostics[0].code)


if __name__ == "__main__":
    unittest.main()
