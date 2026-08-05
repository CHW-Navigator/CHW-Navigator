from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
GOVERNANCE = ROOT / "contracts" / "examples" / "governance"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.registry_governance import (
    DataConcept,
    DataDictionary,
    RegistryGovernanceError,
    parse_registry_set_v2,
    seal_registry_set_v2,
)


def governed_payload() -> dict:
    return json.loads((GOVERNANCE / "valid-registry-set-v2.json").read_text(encoding="utf-8"))


class DataDictionaryTests(unittest.TestCase):
    def test_positive_concept_has_policy_references_not_invented_policy_text(self) -> None:
        document = parse_registry_set_v2(governed_payload())
        concept = document.data_dictionary.concepts[0]
        self.assertEqual("clinical.lmp_date", concept.id)
        self.assertEqual("retention.synthetic-test@1.0.0", concept.retention_policy_ref)
        self.assertEqual("consent.synthetic-test@1.0.0", concept.consent_policy_ref)
        self.assertEqual("access.synthetic-test@1.0.0", concept.access_policy_ref)
        self.assertEqual("approved", concept.lifecycle_state)

    def test_concept_surface_matches_stored_schema(self) -> None:
        schema = json.loads((ROOT / "contracts" / "data-dictionary.schema.json").read_text(encoding="utf-8"))
        expected = set(DataConcept.model_fields)
        self.assertEqual(expected, set(schema["$defs"]["concept"]["required"]))
        self.assertEqual(expected, set(schema["$defs"]["concept"]["properties"]))
        self.assertEqual(set(DataDictionary.model_fields), set(schema["required"]))

    def test_mutating_concept_changes_concept_dictionary_and_set_digests(self) -> None:
        first = governed_payload()
        changed = copy.deepcopy(first)
        changed["data_dictionary"]["concepts"][0]["definition"] += " Synthetic change."
        second = seal_registry_set_v2(changed)
        self.assertNotEqual(
            first["data_dictionary"]["concepts"][0]["content_digest"],
            second["data_dictionary"]["concepts"][0]["content_digest"],
        )
        self.assertNotEqual(first["data_dictionary"]["content_digest"], second["data_dictionary"]["content_digest"])
        self.assertNotEqual(first["content_digest"], second["content_digest"])

    def test_unknown_fields_and_invalid_value_sets_fail_closed(self) -> None:
        extra = governed_payload()
        extra["data_dictionary"]["concepts"][0]["approval_record"] = {"approved": True}
        extra = seal_registry_set_v2(extra)
        with self.assertRaises(RegistryGovernanceError):
            parse_registry_set_v2(extra)

        choice = governed_payload()
        choice["data_dictionary"]["concepts"][0]["type"] = "choice"
        choice["data_dictionary"]["concepts"][0]["value_set"] = []
        choice = seal_registry_set_v2(choice)
        with self.assertRaises(RegistryGovernanceError):
            parse_registry_set_v2(choice)


if __name__ == "__main__":
    unittest.main()
