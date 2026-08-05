from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
CONTRACTS = ROOT / "contracts"
FIXTURE = CONTRACTS / "examples" / "tracer" / "valid-registry-set.json"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.diagnostics import DiagnosticCode
from chw_navigator.registry_set import (
    CapabilityRegistry,
    RegistrySet,
    RegistrySetError,
    TargetProfile,
    parse_registry_set,
    resolve_capability,
    seal_registry_set,
)


class TargetProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_target_profile_pins_exact_platform_contract(self) -> None:
        profile = parse_registry_set(self.payload).target_profile
        self.assertEqual("5.2.0", profile.cht_core_version)
        self.assertEqual("6.4.1", profile.cht_conf_version)
        self.assertEqual(("cht-form-runner", "4.11.0"), (profile.form_engine.name, profile.form_engine.version))
        self.assertTrue(profile.extension_support.extension_lib_xpath)
        self.assertTrue(profile.extension_support.extension_lib_expression)
        self.assertEqual(
            {"contact_summary", "registered_local_read", "latest_value_ordering", "recorded_at_freshness"},
            set(profile.required_local_data_features),
        )

    def test_unsupported_target_profile_fails_closed(self) -> None:
        changed = copy.deepcopy(self.payload)
        changed["target_profile"]["id"] = "cht-core-4.22"
        document = parse_registry_set(seal_registry_set(changed))
        with self.assertRaises(RegistrySetError) as raised:
            resolve_capability(document, "technical.gestational-age.naegele")
        self.assertEqual(DiagnosticCode.TARGET_PROFILE_UNSUPPORTED, raised.exception.diagnostics[0].code)

    def test_missing_required_runtime_feature_fails_closed(self) -> None:
        changed = copy.deepcopy(self.payload)
        changed["target_profile"]["required_local_data_features"].remove("recorded_at_freshness")
        document = parse_registry_set(seal_registry_set(changed))
        with self.assertRaises(RegistrySetError) as raised:
            resolve_capability(
                document,
                "technical.gestational-age.naegele",
                required_target_features=("recorded_at_freshness",),
            )
        self.assertEqual(DiagnosticCode.TARGET_FEATURE_MISSING, raised.exception.diagnostics[0].code)

    def test_disabled_extension_feature_fails_closed(self) -> None:
        changed = copy.deepcopy(self.payload)
        changed["target_profile"]["extension_support"]["extension_lib_expression"] = False
        document = parse_registry_set(seal_registry_set(changed))
        with self.assertRaises(RegistrySetError) as raised:
            resolve_capability(
                document,
                "technical.gestational-age.naegele",
                required_target_features=("extension_lib_expression",),
            )
        self.assertEqual(DiagnosticCode.TARGET_FEATURE_MISSING, raised.exception.diagnostics[0].code)

    def test_schema_documents_reject_unknown_fields(self) -> None:
        for name in ("registry-set.schema.json", "capability-registry.schema.json", "target-profile.schema.json"):
            schema = json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
            self.assertFalse(schema["additionalProperties"], name)

    def test_stored_schema_roots_match_runtime_models(self) -> None:
        pairs = (
            ("registry-set.schema.json", RegistrySet),
            ("capability-registry.schema.json", CapabilityRegistry),
            ("target-profile.schema.json", TargetProfile),
        )
        for name, model in pairs:
            with self.subTest(schema=name):
                schema = json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
                self.assertEqual(set(model.model_fields), set(schema["required"]))
                self.assertEqual(set(model.model_fields), set(schema["properties"]))


if __name__ == "__main__":
    unittest.main()
