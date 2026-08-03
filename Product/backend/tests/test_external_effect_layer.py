"""Prompt 10 planning-only regression tests."""

from __future__ import annotations

from copy import deepcopy
import unittest

from backend.operational import OperationalValidationError, build_external_effect_package


CATALOG = {
    "id": "reviewed-effect-catalog",
    "version": "1.0.0",
    "templates": [
        {
            "id": "follow-up-reminder",
            "version": "1.0.0",
            "status": "active",
            "approved": True,
            "approved_by": "program-review",
            "approved_at": "2026-08-03T00:00:00Z",
            "purpose": "follow_up_reminder",
            "channels": ["sms"],
            "variables": [
                {
                    "name": "child_name",
                    "type": "string",
                    "sensitivity": "personal",
                    "required": True,
                }
            ],
            "translations": {"en": "Please arrange follow-up for {{child_name}}."},
        }
    ],
    "policies": [
        {
            "id": "caregiver-messaging",
            "version": "1.0.0",
            "status": "active",
            "approved": True,
            "allowed_purposes": ["follow_up_reminder"],
            "allowed_channels_by_purpose": {"follow_up_reminder": ["sms"]},
            "channel_sensitivity_ceiling": {"sms": "personal"},
            "consent_required_purposes": ["follow_up_reminder"],
            "emergency_consent_override_purposes": [],
            "max_attempts": 2,
        }
    ],
    "adapters": [
        {
            "id": "rapidpro-sms",
            "version": "1.0.0",
            "status": "active",
            "approved": True,
            "channels": ["sms"],
            "secret_references": ["secret://messaging/rapidpro"],
        }
    ],
}

TOPOLOGY_LOCK = {
    "schema_version": "1.0",
    "resolver_version": "gen8.operational.topology@1.0",
    "topology_package": {
        "id": "country-topology",
        "version": "1.0.0",
        "snapshot_id": "2026-08-03",
        "content_digest": "sha256:" + "b" * 64,
        "schema_digest": "sha256:" + "c" * 64,
        "access_policy_digest": "sha256:" + "d" * 64,
        "capability_vocabulary_digest": "sha256:" + "e" * 64,
    },
}

REQUEST = {
    "schema_version": "1.0",
    "source": {
        "package_id": "clinical-logic",
        "package_version": "8.0.0",
        "trigger_id": "followup-day-3",
        "trigger_event_id": "clinical-event-template",
        "provenance": [{"quotation": "Return for follow-up in three days.", "page": 42}],
    },
    "capability": "external-effect.send-approved-message@1.0.0",
    "subject": "current_patient",
    "recipient_relation": "patient.primary-caregiver",
    "purpose": "follow_up_reminder",
    "channel": "sms",
    "urgency": "routine",
    "template": {
        "id": "follow-up-reminder",
        "version": "1.0.0",
        "locale": "en",
        "variables": {"child_name": "the child"},
    },
    "adapter": {"id": "rapidpro-sms", "version": "1.0.0"},
    "requested_at": "2026-08-03T09:00:00Z",
    "not_before": "2026-08-06T09:00:00Z",
    "expires_at": "2026-08-10T09:00:00Z",
    "policy": {"id": "caregiver-messaging", "version": "1.0.0"},
    "topology_snapshot_id": "2026-08-03",
    "acknowledgment": {"required": False},
}


def build(requests=None, catalog=None, topology_lock=None):
    return build_external_effect_package(
        requests if requests is not None else [REQUEST],
        catalog if catalog is not None else CATALOG,
        resolved_capabilities={"external-effect.send-approved-message@1.0.0"},
        topology_lock=topology_lock if topology_lock is not None else TOPOLOGY_LOCK,
        clinical_logic_content_sha256="a" * 64,
    )


class TestExternalEffectPlanning(unittest.TestCase):
    def test_compiles_deterministic_request_and_exact_lock_without_dispatch(self):
        first = build()
        second = build()
        effect = first["external_effect_requests"][0]
        self.assertEqual(first, second)
        self.assertTrue(effect["id"].startswith("effect-"))
        self.assertEqual(effect["state"], "requested")
        self.assertEqual(first["compile_status"], "planned")
        self.assertEqual(first["runtime_status"], "planning_only")
        self.assertEqual(first["version_lock"]["topology_package"]["snapshot_id"], "2026-08-03")

    def test_rejects_raw_destination_before_any_effect_can_be_planned(self):
        unsafe = deepcopy(REQUEST)
        unsafe["template"]["variables"]["child_name"] = "Contact +15551234567"
        with self.assertRaisesRegex(OperationalValidationError, "forbidden direct data"):
            build([unsafe])

    def test_rejects_unresolved_capability_and_mismatched_topology_snapshot(self):
        unresolved = deepcopy(REQUEST)
        unresolved["capability"] = "external-effect.unknown@1.0.0"
        with self.assertRaisesRegex(OperationalValidationError, "exact resolved capability"):
            build([unresolved])
        mismatched = deepcopy(REQUEST)
        mismatched["topology_snapshot_id"] = "different-snapshot"
        with self.assertRaisesRegex(OperationalValidationError, "different topology snapshot"):
            build([mismatched])

    def test_rejects_unknown_adapter_and_incomplete_topology_lock(self):
        unknown_adapter = deepcopy(REQUEST)
        unknown_adapter["adapter"] = {"id": "other", "version": "1.0.0"}
        with self.assertRaisesRegex(OperationalValidationError, "unknown approved adapter"):
            build([unknown_adapter])
        incomplete_lock = deepcopy(TOPOLOGY_LOCK)
        del incomplete_lock["topology_package"]["access_policy_digest"]
        with self.assertRaisesRegex(OperationalValidationError, "access_policy_digest"):
            build(topology_lock=incomplete_lock)

    def test_rejects_template_expression_and_unapproved_locale(self):
        expressive_catalog = deepcopy(CATALOG)
        expressive_catalog["templates"][0]["translations"]["en"] = "{{child_name.upper()}}"
        with self.assertRaisesRegex(OperationalValidationError, "undeclared variable|invalid placeholder"):
            build(catalog=expressive_catalog)
        locale = deepcopy(REQUEST)
        locale["template"]["locale"] = "fr"
        with self.assertRaisesRegex(OperationalValidationError, "locale is not approved"):
            build([locale])

    def test_rejects_wrongly_typed_or_over_sensitive_template_values(self):
        wrongly_typed = deepcopy(REQUEST)
        wrongly_typed["template"]["variables"]["child_name"] = 42
        with self.assertRaisesRegex(OperationalValidationError, "does not match its declared type"):
            build([wrongly_typed])
        too_sensitive_catalog = deepcopy(CATALOG)
        too_sensitive_catalog["policies"][0]["channel_sensitivity_ceiling"]["sms"] = "non-sensitive"
        with self.assertRaisesRegex(OperationalValidationError, "above the channel sensitivity ceiling"):
            build(catalog=too_sensitive_catalog)


if __name__ == "__main__":
    unittest.main()
