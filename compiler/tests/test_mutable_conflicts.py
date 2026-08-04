from __future__ import annotations

from dataclasses import replace
from itertools import permutations
import json
from pathlib import Path
import unittest

from chw_navigator.diagnostics import DiagnosticCode
from chw_navigator.mutable_conflicts import (
    CHTConflictFixture,
    ConflictPolicyRegistry,
    CorrectionEvent,
    FHIRVersionConflictFixture,
    RegisteredFieldConflictPolicy,
    correction_events_from_cht_conflict_fixture,
    resolve_mutable_field_conflicts,
    review_obligation_from_fhir_conflict_fixture,
    validate_conflict_policy_registry,
)


ROOT = Path(__file__).resolve().parents[1]


def _registry() -> ConflictPolicyRegistry:
    raw = json.loads((ROOT / "contracts" / "conflict-policies.json").read_text(encoding="utf-8"))
    return ConflictPolicyRegistry.from_mapping(raw)


def _event(event_id: str, field: str, value: object, **overrides: object) -> CorrectionEvent:
    values: dict[str, object] = {
        "event_id": event_id,
        "person_ref": "person.1",
        "field": field,
        "value": value,
        "asserted_at": "2026-08-04T10:00:00Z",
        "effective_at": "2026-08-04T00:00:00Z",
        "received_at": "2026-08-04T10:05:00Z",
        "actor_ref": "user.1",
        "source_ref": "device.1",
        "authority_class": "chw_verified",
        "authorized_workflow": True,
        "supersedes": None,
        "reason_code": "verified_correction",
        "provenance_ref": f"provenance.{event_id}",
    }
    values.update(overrides)
    return CorrectionEvent(**values)  # type: ignore[arg-type]


class MutableConflictTests(unittest.TestCase):
    def test_registry_covers_inventory_and_different_fields_merge(self) -> None:
        schema = json.loads((ROOT / "contracts" / "conflict-policies.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(
            "canonical.mutable-field-resolver@1.0.0",
            schema["properties"]["resolver"]["const"],
        )
        registry = _registry()
        self.assertEqual((), validate_conflict_policy_registry(registry))
        self.assertEqual(10, len(registry.fields))
        result = resolve_mutable_field_conflicts(
            registry,
            (_event("event.name", "name", "Amina"), _event("event.phone", "telephone", "+100")),
        )
        self.assertEqual(2, len(result.all_assertions))
        self.assertEqual("Amina", result.projections["person.1"]["name"])
        self.assertEqual("+100", result.projections["person.1"]["telephone"])

    def test_same_field_projection_preserves_unresolved_assertions(self) -> None:
        result = resolve_mutable_field_conflicts(
            _registry(),
            (
                _event("phone.1", "telephone", "+100"),
                _event("phone.2", "telephone", "+200", received_at="2026-08-04T10:06:00Z"),
            ),
        )
        self.assertEqual("+200", result.projections["person.1"]["telephone"])
        self.assertEqual(1, len(result.unresolved_conflicts))
        self.assertEqual("not_queued", result.review_obligations[0].execution)

    def test_authority_and_supersession_beat_device_times(self) -> None:
        trusted = _event(
            "dob.facility",
            "date_of_birth",
            "2024-01-01",
            authority_class="facility_verified",
            asserted_at="2020-01-01T00:00:00Z",
            effective_at="2020-01-01T00:00:00Z",
        )
        lower = _event(
            "dob.caregiver",
            "date_of_birth",
            "2024-02-01",
            authority_class="caregiver_report",
            asserted_at="2035-01-01T00:00:00Z",
            effective_at="2035-01-01T00:00:00Z",
            received_at="2026-08-04T10:06:00Z",
        )
        authority = resolve_mutable_field_conflicts(_registry(), (lower, trusted))
        self.assertEqual("2024-01-01", authority.projections["person.1"]["date_of_birth"])

        correction = _event(
            "dob.correction",
            "date_of_birth",
            "2024-02-01",
            authority_class="caregiver_report",
            supersedes="dob.facility",
        )
        superseded = resolve_mutable_field_conflicts(_registry(), (trusted, correction))
        self.assertEqual("2024-02-01", superseded.projections["person.1"]["date_of_birth"])
        self.assertEqual((), superseded.unresolved_conflicts)

    def test_duplicate_delivery_and_permutations_are_deterministic(self) -> None:
        original = _event("duplicate.1", "telephone", "+100")
        self.assertEqual(1, len(resolve_mutable_field_conflicts(_registry(), (original, original)).all_assertions))
        divergent = _event("duplicate.1", "telephone", "+200")
        first = resolve_mutable_field_conflicts(_registry(), (original, divergent))
        second = resolve_mutable_field_conflicts(_registry(), (divergent, original))
        self.assertEqual(first, second)
        self.assertEqual(2, len(first.all_assertions))
        self.assertIn(DiagnosticCode.CONFLICT_ASSERTION_DROPPED, tuple(item.code for item in first.diagnostics))

        events = (
            _event("event.1", "telephone", "+100"),
            _event("event.2", "telephone", "+200", received_at="2026-08-04T10:06:00Z"),
            _event("event.3", "administrative_status", "active"),
        )
        expected = resolve_mutable_field_conflicts(_registry(), events)
        for ordering in permutations(events):
            self.assertEqual(expected, resolve_mutable_field_conflicts(_registry(), ordering))

    def test_missing_supersession_cht_and_fhir_fixtures_remain_visible(self) -> None:
        missing = resolve_mutable_field_conflicts(
            _registry(), (_event("phone.correction", "telephone", "+200", supersedes="missing.event"),)
        )
        self.assertIn("missing", missing.unresolved_conflicts[0].reason)

        foreign = _event("foreign.event", "telephone", "+100", person_ref="person.2")
        cross_person = resolve_mutable_field_conflicts(
            _registry(),
            (foreign, _event("invalid.correction", "telephone", "+200", supersedes="foreign.event")),
        )
        self.assertIn(
            DiagnosticCode.CONFLICT_RESOLVER_INVALID,
            tuple(item.code for item in cross_person.diagnostics),
        )
        self.assertTrue(cross_person.unresolved_conflicts)

        winner = _event("cht.winner", "telephone", "+100")
        loser = _event("cht.loser", "telephone", "+200")
        translated = correction_events_from_cht_conflict_fixture(CHTConflictFixture(winner, (loser,)))
        self.assertEqual(("cht.loser", "cht.winner"), tuple(item.event_id for item in translated))
        obligation = review_obligation_from_fhir_conflict_fixture(FHIRVersionConflictFixture(loser, 412))
        self.assertIn("fhir:412", obligation.id)
        self.assertEqual("not_queued", obligation.execution)

    def test_all_conflict_diagnostics_are_emitted_and_fail_closed(self) -> None:
        missing = resolve_mutable_field_conflicts(_registry(), (_event("unknown", "unregistered", "x"),))
        self.assertIn(DiagnosticCode.CONFLICT_POLICY_MISSING, tuple(item.code for item in missing.diagnostics))

        invalid_resolver = replace(_registry(), resolver="unknown@1")
        self.assertIn(
            DiagnosticCode.CONFLICT_RESOLVER_INVALID,
            tuple(item.code for item in validate_conflict_policy_registry(invalid_resolver)),
        )

        device_only = replace(_registry(), ordering_rules=("device_time",))
        self.assertIn(
            DiagnosticCode.CONFLICT_DEVICE_TIME_AUTHORITY,
            tuple(item.code for item in validate_conflict_policy_registry(device_only)),
        )
        reordered = replace(_registry(), ordering_rules=tuple(reversed(_registry().ordering_rules)))
        self.assertIn(
            DiagnosticCode.CONFLICT_RESOLVER_INVALID,
            tuple(item.code for item in validate_conflict_policy_registry(reordered)),
        )

        clinical = RegisteredFieldConflictPolicy(
            field="clinical_observation",
            field_class="clinical_evidence",
            conflict_policy="append_correction",
            allowed_authority_classes=("chw_verified",),
            append_only_clinical_evidence=True,
        )
        clinical_registry = replace(_registry(), fields=(*_registry().fields, clinical))
        self.assertIn(
            DiagnosticCode.CONFLICT_CLINICAL_EVIDENCE_MUTABLE,
            tuple(item.code for item in validate_conflict_policy_registry(clinical_registry)),
        )


if __name__ == "__main__":
    unittest.main()
