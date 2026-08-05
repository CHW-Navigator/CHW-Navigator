"""Focused Prompt 9 topology regression tests."""

from __future__ import annotations

from copy import deepcopy
import unittest

from backend.operational import (
    OperationalValidationError,
    assert_persona_isolation,
    build_topology_lock,
    build_operational_package,
    resolve_topology_relation,
    resolve_topology_relation_for_user,
    simulate_topology_access,
    validate_topology_requirements_against_package,
    validate_topology_package,
)


TOPOLOGY = {
    "id": "country-topology",
    "version": "1.0.0",
    "snapshot_id": "2026-08-03",
    "generated_at": "2026-08-03T00:00:00Z",
    "schema": {
        "id": "country-chw-model",
        "version": "1.0.0",
        "service_area_type_id": "service_area",
        "contact_types": [
            {"id": "district", "kind": "place", "semantic": "administrative-area", "allowed_parents": []},
            {"id": "facility", "kind": "place", "semantic": "facility", "allowed_parents": ["district"], "capabilities": True},
            {"id": "service_area", "kind": "place", "semantic": "service-area", "allowed_parents": ["facility"]},
            {"id": "household", "kind": "place", "semantic": "household", "allowed_parents": ["service_area"]},
            {"id": "patient", "kind": "person", "semantic": "patient", "allowed_parents": ["household"]},
            {"id": "caregiver", "kind": "person", "semantic": "caregiver", "allowed_parents": ["household"]},
            {"id": "chw", "kind": "person", "semantic": "practitioner", "allowed_parents": ["facility"]},
            {"id": "supervisor", "kind": "person", "semantic": "supervisor", "allowed_parents": ["facility"]},
        ],
    },
    "nodes": [
        {"external_id": "district-a", "contact_type": "district", "name": "District A", "active_from": "2025-01-01T00:00:00Z"},
        {"external_id": "facility-a", "contact_type": "facility", "name": "Facility A", "active_from": "2025-01-01T00:00:00Z"},
        {"external_id": "area-a", "contact_type": "service_area", "name": "Area A", "active_from": "2025-01-01T00:00:00Z"},
        {"external_id": "household-a", "contact_type": "household", "name": "Household A", "active_from": "2025-01-01T00:00:00Z"},
        {"external_id": "patient-a", "contact_type": "patient", "name": "Patient A", "aliases": ["patient-a-old"], "active_from": "2025-01-01T00:00:00Z"},
        {"external_id": "caregiver-a", "contact_type": "caregiver", "name": "Caregiver A", "active_from": "2025-01-01T00:00:00Z"},
        {"external_id": "chw-old", "contact_type": "chw", "name": "CHW Old", "active_from": "2025-01-01T00:00:00Z"},
        {"external_id": "chw-new", "contact_type": "chw", "name": "CHW New", "active_from": "2025-01-01T00:00:00Z"},
        {"external_id": "supervisor-a", "contact_type": "supervisor", "name": "Supervisor A", "active_from": "2025-01-01T00:00:00Z"},
    ],
    "placements": [
        {"id": "p-facility", "child_external_id": "facility-a", "parent_external_id": "district-a", "active_from": "2025-01-01T00:00:00Z", "approved_by": "ops"},
        {"id": "p-area", "child_external_id": "area-a", "parent_external_id": "facility-a", "active_from": "2025-01-01T00:00:00Z", "approved_by": "ops"},
        {"id": "p-household", "child_external_id": "household-a", "parent_external_id": "area-a", "active_from": "2025-01-01T00:00:00Z", "approved_by": "ops"},
        {"id": "p-patient", "child_external_id": "patient-a", "parent_external_id": "household-a", "active_from": "2025-01-01T00:00:00Z", "approved_by": "ops"},
        {"id": "p-caregiver", "child_external_id": "caregiver-a", "parent_external_id": "household-a", "active_from": "2025-01-01T00:00:00Z", "approved_by": "ops"},
        {"id": "p-chw-old", "child_external_id": "chw-old", "parent_external_id": "facility-a", "active_from": "2025-01-01T00:00:00Z", "approved_by": "ops"},
        {"id": "p-chw-new", "child_external_id": "chw-new", "parent_external_id": "facility-a", "active_from": "2025-01-01T00:00:00Z", "approved_by": "ops"},
        {"id": "p-supervisor", "child_external_id": "supervisor-a", "parent_external_id": "facility-a", "active_from": "2025-01-01T00:00:00Z", "approved_by": "ops"},
    ],
    "assignments": [
        {"id": "serve-old", "service_area_external_id": "area-a", "assignee_external_id": "chw-old", "relation": "serves", "primary": True, "active_from": "2025-01-01T00:00:00Z", "active_to": "2026-08-01T00:00:00Z", "approved_by": "ops"},
        {"id": "serve-new", "service_area_external_id": "area-a", "assignee_external_id": "chw-new", "relation": "serves", "primary": True, "active_from": "2026-08-01T00:00:00Z", "approved_by": "ops"},
        {"id": "supervise", "service_area_external_id": "area-a", "assignee_external_id": "supervisor-a", "relation": "supervises", "primary": True, "active_from": "2025-01-01T00:00:00Z", "approved_by": "ops"},
    ],
    "facility_capabilities": [
        {"id": "cap-emergency", "facility_external_id": "facility-a", "capability_code": "emergency-care", "active_from": "2025-01-01T00:00:00Z"},
    ],
    "cross_references": [
        {"from_external_id": "patient-a", "to_external_id": "caregiver-a", "relation": "patient.primary-caregiver", "active_from": "2025-01-01T00:00:00Z"}
    ],
    "users": [
        {"username": "chw.new", "person_external_id": "chw-new", "role": "chw", "assigned_place_external_ids": ["area-a"], "active_from": "2026-08-01T00:00:00Z"},
    ],
    "access_policy": {
        "id": "country-access",
        "version": "1.0.0",
        "default_deny": True,
        "roles": [
            {
                "role": "chw",
                "placement_scope": "assigned-subtree",
                "allowed_contact_types": ["service_area", "household", "patient"],
                "allowed_record_kinds": ["report", "task", "referral", "episode-event"],
                "allowed_relations": [
                    "contact.responsible-area",
                    "patient.assigned-chw",
                "patient.supervising-entity",
                "referral.eligible-facilities",
                "patient.primary-caregiver",
                ],
                "max_descendant_depth": 3,
                "include_ancestors": False,
            }
        ],
    },
    "capability_vocabulary": {"id": "country-capabilities", "version": "1.0.0", "codes": ["emergency-care"]},
    "relation_rules": [
        {"relation": "contact.responsible-area", "cardinality": "one", "supported_backends": ["cht", "fhir-r4"]},
        {"relation": "patient.assigned-chw", "cardinality": "one", "supported_backends": ["cht", "fhir-r4"]},
        {"relation": "patient.supervising-entity", "cardinality": "one", "supported_backends": ["cht", "fhir-r4"]},
        {"relation": "referral.eligible-facilities", "cardinality": "collection", "supported_backends": ["cht", "fhir-r4"]},
        {"relation": "patient.primary-caregiver", "cardinality": "one", "supported_backends": ["cht", "fhir-r4"]},
    ],
}


def package() -> dict:
    return deepcopy(TOPOLOGY)


class TestTopologyValidation(unittest.TestCase):
    def test_valid_topology_has_no_errors_and_produces_exact_lock(self):
        diagnostics = validate_topology_package(package(), deployment=True)
        self.assertEqual([item for item in diagnostics if item["severity"] == "error"], [])
        lock = build_topology_lock(package())
        self.assertEqual(lock["topology_package"]["id"], "country-topology")
        self.assertTrue(lock["topology_package"]["content_digest"].startswith("sha256:"))
        self.assertTrue(lock["topology_package"]["schema_digest"].startswith("sha256:"))
        changed = package()
        changed["assignments"][1]["approved_by"] = "different-reviewer"
        self.assertNotEqual(
            lock["topology_package"]["content_digest"],
            build_topology_lock(changed)["topology_package"]["content_digest"],
        )

    def test_requirement_binds_to_a_relation_rule_and_not_a_deployment_identity(self):
        requirement = {
            "id": "topology_requirement.followup_owner",
            "relation": "patient.assigned-chw",
            "cardinality": "one",
            "registry": "topology.resolve.assigned-chw@1.0.0",
            "subject": "current_patient",
            "evidence": [{"quotation": "Follow up in three days.", "page": 98}],
        }
        validate_topology_requirements_against_package([requirement], package())
        mismatched = dict(requirement, cardinality="collection")
        with self.assertRaisesRegex(OperationalValidationError, "cardinality"):
            validate_topology_requirements_against_package([mismatched], package())

    def test_clinical_topology_requirement_rejects_a_direct_identity(self):
        registry = {
            "id": "topology-registry",
            "version": "1.0.0",
            "entries": [{
                "id": "topology.resolve.assigned-chw",
                "version": "1.0.0",
                "family": "topology",
                "operation": "resolve",
                "resource": "assigned-chw",
                "input_types": ["patient-relation-request"],
                "output_types": ["abstract-assignee"],
                "backends": ["cht"],
                "status": "active",
                "approved": True,
            }],
        }
        candidate = {
            "id": "resolve-assignee",
            "family": "topology",
            "operation": "resolve",
            "resource": "assigned-chw",
            "input_types": ["patient-relation-request"],
            "output_types": ["abstract-assignee"],
            "backend": "cht",
            "requires_human_review": False,
            "source": {"document_id": "guide", "page": "98", "section": "follow-up", "quote": "Follow up."},
        }
        requirement = {
            "id": "topology_requirement.followup_owner",
            "relation": "patient.assigned-chw",
            "cardinality": "one",
            "registry": "topology.resolve.assigned-chw@1.0.0",
            "subject": "current_patient",
            "subject_external_id": "patient-a",
            "evidence": [{"quotation": "Follow up in three days.", "page": 98}],
        }
        with self.assertRaisesRegex(OperationalValidationError, "deployment identities"):
            build_operational_package(
                {"capability_candidates": [candidate], "topology_requirements": [requirement]},
                registry,
                clinical_logic_content_sha256="a" * 64,
            )

    def test_rejects_platform_identifier_and_second_responsibility_field(self):
        invalid = package()
        invalid["nodes"][4]["_id"] = "couch-document-id"
        invalid["nodes"][4]["responsible_area_external_id"] = "area-a"
        codes = {item["code"] for item in validate_topology_package(invalid)}
        self.assertIn("H-ID", codes)
        self.assertIn("H-RESP", codes)

    def test_rejects_overlapping_parents(self):
        invalid = package()
        invalid["placements"].append({
            "id": "p-patient-second-parent",
            "child_external_id": "patient-a",
            "parent_external_id": "household-a",
            "active_from": "2026-01-01T00:00:00Z",
            "approved_by": "ops",
        })
        codes = {item["code"] for item in validate_topology_package(invalid)}
        self.assertIn("H-RESP", codes)

    def test_checks_future_effective_date_boundaries_not_only_the_current_snapshot(self):
        invalid = package()
        invalid["placements"][3]["active_to"] = "2026-09-01T00:00:00Z"
        codes = {item["code"] for item in validate_topology_package(invalid)}
        self.assertIn("H-TREE", codes)


class TestTopologyResolution(unittest.TestCase):
    def test_resolves_current_and_historical_assignee_from_effective_dates(self):
        current = resolve_topology_relation(package(), {
            "relation": "patient.assigned-chw", "cardinality": "one", "subject_external_id": "patient-a", "at": "2026-08-03T00:00:00Z", "target_backend": "cht"
        })
        historic = resolve_topology_relation(package(), {
            "relation": "patient.assigned-chw", "cardinality": "one", "subject_external_id": "patient-a-old", "at": "2026-07-31T00:00:00Z", "target_backend": "fhir-r4"
        })
        self.assertEqual((current["status"], current["matches"]), ("resolved", ["chw-new"]))
        self.assertEqual((historic["status"], historic["matches"]), ("resolved", ["chw-old"]))

    def test_never_breaks_a_coverage_tie_by_array_order(self):
        ambiguous = package()
        ambiguous["nodes"].append({"external_id": "chw-cover", "contact_type": "chw", "name": "CHW Cover", "active_from": "2025-01-01T00:00:00Z"})
        ambiguous["placements"].append({"id": "p-chw-cover", "child_external_id": "chw-cover", "parent_external_id": "facility-a", "active_from": "2025-01-01T00:00:00Z", "approved_by": "ops"})
        ambiguous["assignments"][1]["primary"] = False
        ambiguous["assignments"][1]["coverage"] = True
        ambiguous["assignments"].append({"id": "serve-cover", "service_area_external_id": "area-a", "assignee_external_id": "chw-cover", "relation": "serves", "coverage": True, "active_from": "2026-08-01T00:00:00Z", "approved_by": "ops"})
        result = resolve_topology_relation(ambiguous, {
            "relation": "patient.assigned-chw", "cardinality": "one", "subject_external_id": "patient-a", "at": "2026-08-03T00:00:00Z", "target_backend": "cht"
        })
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["matches"], ["chw-cover", "chw-new"])

    def test_referral_requires_an_active_capability_and_never_guesses_a_facility(self):
        eligible = resolve_topology_relation(package(), {
            "relation": "referral.eligible-facilities", "cardinality": "collection", "required_capability_codes": ["emergency-care"], "at": "2026-08-03T00:00:00Z", "target_backend": "fhir-r4"
        })
        unavailable = package()
        unavailable["facility_capabilities"][0]["active_to"] = "2026-08-01T00:00:00Z"
        missing = resolve_topology_relation(unavailable, {
            "relation": "referral.eligible-facilities", "cardinality": "collection", "required_capability_codes": ["emergency-care"], "at": "2026-08-03T00:00:00Z", "target_backend": "fhir-r4"
        })
        self.assertEqual((eligible["status"], eligible["matches"]), ("resolved", ["facility-a"]))
        self.assertEqual((missing["status"], missing["matches"]), ("unassigned", []))

    def test_caregiver_requires_an_explicit_effective_dated_reference(self):
        resolved = resolve_topology_relation(package(), {
            "relation": "patient.primary-caregiver", "cardinality": "one", "subject_external_id": "patient-a", "at": "2026-08-03T00:00:00Z", "target_backend": "cht"
        })
        missing = package()
        missing["cross_references"] = []
        unresolved = resolve_topology_relation(missing, {
            "relation": "patient.primary-caregiver", "cardinality": "one", "subject_external_id": "patient-a", "at": "2026-08-03T00:00:00Z", "target_backend": "cht"
        })
        self.assertEqual((resolved["status"], resolved["matches"]), ("resolved", ["caregiver-a"]))
        self.assertEqual((unresolved["status"], unresolved["matches"]), ("unassigned", []))


class TestTopologyAccess(unittest.TestCase):
    def test_access_simulation_uses_replicated_ids_and_blocks_out_of_scope_resolution(self):
        records = [{"id": "report-a", "kind": "report", "subject_external_id": "patient-a"}]
        simulation = simulate_topology_access(package(), "chw.new", records, at="2026-08-03T00:00:00Z")
        self.assertIn("patient-a", simulation["replicated_node_ids"])
        self.assertNotIn("facility-a", simulation["replicated_node_ids"])
        self.assertEqual(simulation["replicated_record_ids"], ["report-a"])
        assert_persona_isolation(simulation, ["facility-a"])
        with self.assertRaisesRegex(OperationalValidationError, "H-PERSONA"):
            assert_persona_isolation(simulation, ["patient-a"])
        blocked = resolve_topology_relation_for_user(package(), "chw.new", {
            "relation": "patient.assigned-chw", "cardinality": "one", "subject_external_id": "chw-old", "at": "2026-08-03T00:00:00Z", "target_backend": "cht"
        }, records)
        self.assertEqual(blocked["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
