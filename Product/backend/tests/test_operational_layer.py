"""Regression tests for the Prompt 8--10 operational companion boundary."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.operational import (
    OperationalValidationError,
    build_operational_package,
    project_lifecycle,
    resolve_capability,
    validate_lifecycle_definition,
)


SOURCE = {
    "document_id": "who-child-guide-2024",
    "page": "42",
    "section": "Follow-up",
    "quote": "Reassess the child after three days.",
}

REGISTRY = {
    "id": "reviewed-registry",
    "version": "1.0.0",
    "entries": [
        {
            "id": "platform.task.schedule",
            "version": "1.0.0",
            "family": "platform-service",
            "operation": "schedule",
            "resource": "task",
            "input_types": ["task_intent", "duration"],
            "output_types": ["task_receipt"],
            "backends": ["cht", "fhir"],
            "status": "active",
            "approved": True,
        }
    ],
}

CANDIDATE = {
    "id": "cap-followup-task",
    "family": "platform-service",
    "operation": "schedule",
    "resource": "task",
    "input_types": ["task_intent", "duration"],
    "output_types": ["task_receipt"],
    "backend": "cht",
    "requires_human_review": False,
    "source": SOURCE,
}

LIFECYCLE = {
    "id": "acute-followup",
    "version": "1.0.0",
    "predicate_set_version": "predicates@2",
    "dmn_version": "dmn@4",
    "initial_state": "active",
    "states": [
        {"id": "active", "terminal": False},
        {"id": "overdue", "terminal": False},
        {"id": "closed_recovered", "terminal": True, "recovery": True},
        {"id": "closed_lost_to_follow_up", "terminal": True},
    ],
    "transitions": [
        {"from": "active", "to": "overdue", "event_type": "task_expired", "event_category": "timer"},
        {
            "from": "active",
            "to": "closed_recovered",
            "event_type": "clinical_reassessment",
            "event_category": "clinical",
            "requires_guard": True,
            "guard_id": "recovery-guard-v1",
        },
        {
            "from": "overdue",
            "to": "closed_recovered",
            "event_type": "clinical_reassessment",
            "event_category": "clinical",
            "requires_guard": True,
            "guard_id": "recovery-guard-v1",
        },
        {
            "from": "overdue",
            "to": "closed_lost_to_follow_up",
            "event_type": "loss_threshold",
            "event_category": "timer",
        },
    ],
}


class TestCapabilityResolution(unittest.TestCase):
    def test_resolves_one_exact_approved_entry(self):
        resolution = resolve_capability(CANDIDATE, REGISTRY["entries"])
        self.assertEqual(resolution["status"], "resolved")
        self.assertEqual(resolution["entry_id"], "platform.task.schedule")

    def test_blocks_ambiguity_instead_of_selecting_by_identifier(self):
        duplicate = dict(REGISTRY["entries"][0], id="platform.task.schedule.alternative")
        resolution = resolve_capability(CANDIDATE, [REGISTRY["entries"][0], duplicate])
        self.assertEqual(resolution["status"], "blocked")
        self.assertEqual(resolution["reason"], "ambiguous_exact_match")


class TestEpisodeLifecycle(unittest.TestCase):
    def test_recovery_requires_current_clinical_guard_evidence(self):
        result = project_lifecycle(
            LIFECYCLE,
            [
                {
                    "id": "event-1",
                    "episode_id": "episode-1",
                    "event_type": "task_expired",
                    "event_category": "timer",
                    "causal_sequence": 1,
                    "predicate_set_version": "predicates@2",
                    "dmn_version": "dmn@4",
                    "recorded_at": "2026-08-03T09:00:00Z",
                    "occurred_at": "2026-08-03T09:00:00Z",
                },
                {
                    "id": "event-2",
                    "episode_id": "episode-1",
                    "event_type": "clinical_reassessment",
                    "event_category": "clinical",
                    "causal_sequence": 2,
                    "predicate_set_version": "predicates@2",
                    "dmn_version": "dmn@4",
                    "guard_passed": True,
                    "guard_id": "recovery-guard-v1",
                    "guard_predicate_set_version": "predicates@2",
                    "guard_dmn_version": "dmn@4",
                    "guard_evaluated_at": "2026-08-03T09:01:00Z",
                    "recorded_at": "2026-08-03T09:02:00Z",
                    "occurred_at": "2026-08-03T09:02:00Z",
                },
            ],
            "episode-1",
        )
        self.assertEqual(result["state"], "closed_recovered")

    def test_stale_or_nonclinical_events_are_quarantined(self):
        result = project_lifecycle(
            LIFECYCLE,
            [
                {
                    "id": "event-stale",
                    "episode_id": "episode-1",
                    "event_type": "clinical_reassessment",
                    "event_category": "clinical",
                    "causal_sequence": 1,
                    "predicate_set_version": "predicates@old",
                    "dmn_version": "dmn@4",
                    "guard_passed": True,
                    "guard_id": "recovery-guard-v1",
                    "guard_predicate_set_version": "predicates@old",
                    "guard_dmn_version": "dmn@4",
                    "guard_evaluated_at": "2026-08-03T09:00:00Z",
                    "recorded_at": "2026-08-03T09:01:00Z",
                    "occurred_at": "2026-08-03T09:01:00Z",
                }
            ],
            "episode-1",
        )
        self.assertEqual(result["state"], "active")
        self.assertEqual(result["quarantined_events"][0]["reason"], "stale_clinical_version")

    def test_conflicting_event_variants_are_all_quarantined(self):
        common = {
            "id": "event-conflict",
            "episode_id": "episode-1",
            "event_type": "task_expired",
            "event_category": "timer",
            "causal_sequence": 1,
            "predicate_set_version": "predicates@2",
            "dmn_version": "dmn@4",
            "recorded_at": "2026-08-03T09:00:00Z",
            "occurred_at": "2026-08-03T09:00:00Z",
        }
        conflicting = dict(common, event_type="clinical_reassessment", event_category="clinical")
        result = project_lifecycle(LIFECYCLE, [common, conflicting], "episode-1")
        self.assertEqual(result["state"], "active")
        self.assertEqual(
            [item["reason"] for item in result["quarantined_events"]],
            ["conflicting_duplicate", "conflicting_duplicate"],
        )

    def test_rejects_lifecycle_dead_end(self):
        invalid = dict(LIFECYCLE, states=LIFECYCLE["states"] + [{"id": "stuck", "terminal": False}])
        invalid["transitions"] = LIFECYCLE["transitions"] + [
            {"from": "active", "to": "stuck", "event_type": "wait", "event_category": "timer"}
        ]
        with self.assertRaisesRegex(OperationalValidationError, "endpoint path"):
            validate_lifecycle_definition(invalid)

    def test_rejects_a_guard_evaluated_after_the_event_was_recorded(self):
        event = {
            "id": "event-late-guard",
            "episode_id": "episode-1",
            "event_type": "clinical_reassessment",
            "event_category": "clinical",
            "causal_sequence": 1,
            "predicate_set_version": "predicates@2",
            "dmn_version": "dmn@4",
            "guard_passed": True,
            "guard_id": "recovery-guard-v1",
            "guard_predicate_set_version": "predicates@2",
            "guard_dmn_version": "dmn@4",
            "guard_evaluated_at": "2026-08-03T09:02:00Z",
            "recorded_at": "2026-08-03T09:01:00Z",
            "occurred_at": "2026-08-03T09:01:00Z",
        }
        result = project_lifecycle(LIFECYCLE, [event], "episode-1")
        self.assertEqual(result["state"], "active")
        self.assertEqual(result["quarantined_events"][0]["reason"], "invalid_guard_evidence")

    def test_quarantines_same_sequence_events_without_aborting_replay(self):
        collided = {
            "id": "event-collision-a",
            "episode_id": "episode-1",
            "event_type": "task_expired",
            "event_category": "timer",
            "causal_sequence": 1,
            "predicate_set_version": "predicates@2",
            "dmn_version": "dmn@4",
            "recorded_at": "2026-08-03T09:00:00Z",
            "occurred_at": "2026-08-03T09:00:00Z",
        }
        other = dict(collided, id="event-collision-b")
        result = project_lifecycle(LIFECYCLE, [collided, other], "episode-1")
        self.assertEqual(result["state"], "active")
        self.assertEqual(
            [item["reason"] for item in result["quarantined_events"]],
            ["conflicting_causal_sequence", "conflicting_causal_sequence"],
        )


class TestOperationalPackage(unittest.TestCase):
    def test_compiles_planning_only_package_with_abstract_boundaries(self):
        package = build_operational_package(
            {
                "capability_candidates": [CANDIDATE],
                "lifecycle_definitions": [LIFECYCLE],
                "topology_requirements": [
                    {
                        "id": "owner",
                        "relation": "patient.assigned_worker",
                        "requester": "task-planner",
                        "purpose": "follow_up",
                        "topology_package": "district-topology",
                        "topology_version": "3.1.0",
                    }
                ],
                "external_effect_intents": [
                    {
                        "id": "caregiver-reminder",
                        "kind": "message",
                        "purpose": "follow_up_reminder",
                        "recipient_relation": "patient.primary_caregiver",
                        "template_id": "follow-up-reminder-v1",
                        "adapter": "rapidpro",
                        "policy_version": "messaging-policy@1",
                        "state": "planned",
                        "source": SOURCE,
                    }
                ],
            },
            REGISTRY,
            clinical_logic_content_sha256="a" * 64,
        )
        self.assertEqual(package["compile_status"], "planned")
        self.assertEqual(package["external_effect_intents"][0]["state"], "planned")
        self.assertEqual(package["version_lock"]["clinical_logic_content_sha256"], "a" * 64)

    def test_rejects_direct_delivery_address(self):
        requirements = {
            "external_effect_intents": [
                {
                    "id": "unsafe-reminder",
                    "kind": "message",
                    "purpose": "follow_up_reminder",
                    "recipient_relation": "patient.primary_caregiver",
                    "template_id": "follow-up-reminder-v1",
                    "adapter": "rapidpro",
                    "policy_version": "messaging-policy@1",
                    "recipient_phone": "+15551234567",
                    "source": SOURCE,
                }
            ]
        }
        with self.assertRaisesRegex(OperationalValidationError, "direct-delivery"):
            build_operational_package(
                requirements, REGISTRY, clinical_logic_content_sha256="a" * 64
            )


class TestGen8IntegrationBoundary(unittest.TestCase):
    def test_published_operational_schemas_are_valid_json_contracts(self):
        schemas = Path(__file__).parents[1] / "operational" / "schemas"
        expected = {
            "capability-candidate.schema.json",
            "registry-resolution.schema.json",
            "lifecycle-definition.schema.json",
            "episode-event.schema.json",
            "operational-version-lock.schema.json",
            "topology-package.schema.json",
            "topology-requirement.schema.json",
            "topology-relation-request.schema.json",
            "topology-lock.schema.json",
        }
        self.assertEqual({path.name for path in schemas.glob("*.schema.json")}, expected)
        for path in schemas.glob("*.schema.json"):
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertTrue(document["$id"].startswith("https://chw-navigator.org/schema/gen8/"))

    def test_pipeline_exposes_only_gated_operational_sidecars(self):
        """Keep the optional companion boundary visible without loading API deps."""
        pipeline = Path(__file__).parents[1] / "gen8" / "pipeline.py"
        source = pipeline.read_text(encoding="utf-8")
        self.assertIn("operational_requirements: dict | None = None", source)
        self.assertIn("registry_snapshot: dict | None = None", source)
        self.assertIn("topology_package: dict | None = None", source)
        self.assertIn("operational_requirements require an exact registry_snapshot", source)
        self.assertIn("topology requirements require an exact topology_package", source)
        for artifact in (
            "operational_requirements.json",
            "registry_snapshot.json",
            "capability_candidates.json",
            "registry_resolution.json",
            "lifecycle_definitions.json",
            "operational_version_lock.json",
            "operational_package.json",
            "topology_requirements.json",
            "topology_package.json",
            "topology_validation.json",
            "topology_lock.json",
        ):
            self.assertIn(artifact, source)


if __name__ == "__main__":
    unittest.main()
