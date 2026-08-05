from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from chw_navigator.diagnostics import DiagnosticCode
from chw_navigator.person_identity import (
    ConfirmNewProvenance,
    IdentityPersonRecord,
    IdentityProviderConfig,
    IdentityQuery,
    PersonIdentityResolutionRequest,
    deterministic_identity_candidates,
    resolve_person_identity,
    validate_identity_provider,
)


ROOT = Path(__file__).resolve().parents[1]


def _provider(index: int = 0) -> IdentityProviderConfig:
    registry = json.loads((ROOT / "contracts" / "identity-providers.json").read_text(encoding="utf-8"))
    return IdentityProviderConfig.from_mapping(registry["entries"][index])


def _query(**overrides: object) -> IdentityQuery:
    values: dict[str, object] = {
        "authorization_scopes": ("catchment.north",),
        "offline": True,
        "search_scope": "local_replica_only",
        "household_identifier": "household.47",
        "names": ("Amina K",),
        "estimated_age_years": 2,
        "sex": "female",
    }
    values.update(overrides)
    return IdentityQuery(**values)  # type: ignore[arg-type]


def _amina(**overrides: object) -> IdentityPersonRecord:
    values: dict[str, object] = {
        "person_ref": "person.123",
        "display_name": "Amina K.",
        "authorization_scopes": ("catchment.north",),
        "program_person_identifier": "program.123",
        "household_identifier": "household.47",
        "names": ("Amina K",),
        "name_variants": ("Amina",),
        "sex": "female",
        "estimated_age_years": 2,
        "household_hint": "Household ending 47",
    }
    values.update(overrides)
    return IdentityPersonRecord(**values)  # type: ignore[arg-type]


class PersonIdentityTests(unittest.TestCase):
    def test_exact_authorized_identifier_resolves_existing_person(self) -> None:
        schema = json.loads((ROOT / "contracts" / "identity-providers.schema.json").read_text(encoding="utf-8"))
        self.assertEqual("1.0.0", schema["properties"]["schemaVersion"]["const"])
        result = resolve_person_identity(
            PersonIdentityResolutionRequest(
                duplicate_check_claimed=True,
                provider=_provider(),
                query=_query(program_person_identifier="program.123"),
                people=(_amina(),),
            )
        )
        self.assertEqual("resolved_existing", result.status)
        self.assertEqual("person.123", result.person_ref)
        self.assertEqual(("exact_identifier",), result.candidates[0].match_reasons)

    def test_fixture_matching_is_minimal_authorized_and_order_independent(self) -> None:
        twin = _amina(person_ref="person.124", program_person_identifier="program.124")
        outside = _amina(person_ref="person.south", authorization_scopes=("catchment.south",))
        first = deterministic_identity_candidates(
            _provider(), _query(names=("Aminah",), name_variants=("Amina",), estimated_age_years=3), (twin, outside, _amina())
        )
        second = deterministic_identity_candidates(
            _provider(), _query(names=("Aminah",), name_variants=("Amina",), estimated_age_years=3), (_amina(), outside, twin)
        )
        self.assertEqual(first, second)
        self.assertEqual(("person.123", "person.124"), tuple(item.candidate_person_ref for item in first))
        self.assertFalse(hasattr(first[0], "diagnosis"))
        self.assertEqual((), deterministic_identity_candidates(_provider(), _query(), (_amina(household_identifier="other"), outside)))

    def test_ambiguous_twins_defer_and_invalid_selection_blocks(self) -> None:
        people = (_amina(), _amina(person_ref="person.124", program_person_identifier="program.124"))
        deferred = resolve_person_identity(
            PersonIdentityResolutionRequest(True, _query(), people, provider=_provider())
        )
        self.assertEqual("registration_deferred", deferred.status)
        rejected = resolve_person_identity(
            PersonIdentityResolutionRequest(
                True,
                _query(),
                people,
                provider=_provider(),
                disposition="select_existing",
                selected_person_ref="person.not-disclosed",
            )
        )
        self.assertEqual("registration_blocked", rejected.status)

    def test_confirm_new_requires_complete_consistent_provenance(self) -> None:
        provenance = ConfirmNewProvenance(
            actor_ref="user.chw-1",
            asserted_at="2026-08-04T10:00:00Z",
            session_ref="session.device-1",
            candidates_considered=("person.123",),
            reason_code="caregiver_confirmed_distinct_person",
            search_scope="local_replica_only",
            local_only_because_offline=True,
        )
        result = resolve_person_identity(
            PersonIdentityResolutionRequest(
                True,
                _query(),
                (_amina(),),
                provider=_provider(),
                disposition="confirm_new",
                new_person_ref="person.new",
                confirm_new_provenance=provenance,
            )
        )
        self.assertEqual("created_new", result.status)
        self.assertEqual("possible_duplicate_of", result.administrative_events[0].type)
        self.assertTrue(result.administrative_events[0].append_only)

        inconsistent = resolve_person_identity(
            PersonIdentityResolutionRequest(
                True,
                _query(),
                (_amina(),),
                provider=_provider(),
                disposition="confirm_new",
                new_person_ref="person.new",
                confirm_new_provenance=ConfirmNewProvenance(
                    actor_ref="user.chw-1",
                    asserted_at="2026-08-04T10:00:00Z",
                    session_ref="session.device-1",
                    candidates_considered=(),
                    reason_code="confirmed",
                    search_scope="local_replica_only",
                    local_only_because_offline=True,
                ),
            )
        )
        self.assertIn(DiagnosticCode.IDENTITY_PROVENANCE_MISSING, tuple(item.code for item in inconsistent.diagnostics))

    def test_all_identity_diagnostics_are_emitted_and_fail_closed(self) -> None:
        missing_provider = resolve_person_identity(
            PersonIdentityResolutionRequest(True, _query(), ())
        )
        self.assertIn(DiagnosticCode.IDENTITY_PROVIDER_MISSING, tuple(item.code for item in missing_provider.diagnostics))

        invalid_disclosure = replace(_provider(), candidate_disclosure_profile="full-record")
        self.assertIn(
            DiagnosticCode.IDENTITY_DISCLOSURE_INVALID,
            tuple(item.code for item in validate_identity_provider(invalid_disclosure)),
        )
        clinical_feature = replace(_provider(), match_features=("household_identifier", "deriveDiagnosis"))
        self.assertIn(
            DiagnosticCode.IDENTITY_DISCLOSURE_INVALID,
            tuple(item.code for item in validate_identity_provider(clinical_feature)),
        )

        merge = resolve_person_identity(
            PersonIdentityResolutionRequest(True, _query(), (_amina(),), provider=_provider(), merge_requested=True)
        )
        self.assertIn(DiagnosticCode.IDENTITY_MERGE_FORBIDDEN, tuple(item.code for item in merge.diagnostics))

        missing_scope = resolve_person_identity(
            PersonIdentityResolutionRequest(True, _query(search_scope=None), (), provider=_provider())
        )
        self.assertIn(
            DiagnosticCode.IDENTITY_OFFLINE_SCOPE_MISSING,
            tuple(item.code for item in missing_scope.diagnostics),
        )
        self.assertIn(
            DiagnosticCode.IDENTITY_PROVIDER_MISSING,
            tuple(item.code for item in validate_identity_provider(_provider(1))),
        )


if __name__ == "__main__":
    unittest.main()
