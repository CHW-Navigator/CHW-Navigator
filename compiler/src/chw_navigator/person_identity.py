"""Platform-neutral person registration and deterministic identity fixture provider.

This module deliberately owns the Create x Person identity decision outside clinical
IR.  It is a contract fixture, not a production master-patient-index algorithm.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping, Sequence
import unicodedata

from .clinical_vocabulary import contains_clinical_vocabulary
from .diagnostics import Diagnostic, DiagnosticCode


IdentityProviderMode = Literal["required", "external_master_index", "not_supported"]
OfflineSearchScope = Literal["local_replica_only", "cached_authorized_index", "external_index_unavailable"]
IdentityDisposition = Literal["select_existing", "confirm_new", "defer_registration", "escalate"]
IdentityResolutionStatus = Literal[
    "resolved_existing", "created_new", "registration_deferred", "registration_blocked"
]

CREATE_PERSON_IDENTITY_SERVICE = {
    "operation": "Create",
    "resource": "Person",
    "version": "1.0.0",
    "outcomes": (
        "resolved_existing",
        "created_new",
        "registration_deferred",
        "registration_blocked",
    ),
}


@dataclass(frozen=True, slots=True)
class IdentityProviderConfig:
    id: str
    version: str
    mode: IdentityProviderMode
    scope: str
    offline_scope: OfflineSearchScope
    confirmation_required_for_new_record: bool
    candidate_disclosure_profile: str
    match_features: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "IdentityProviderConfig":
        return cls(
            id=str(value.get("id", "")),
            version=str(value.get("version", "")),
            mode=str(value.get("mode", "")),  # type: ignore[arg-type]
            scope=str(value.get("scope", "")),
            offline_scope=str(value.get("offlineScope", "")),  # type: ignore[arg-type]
            confirmation_required_for_new_record=bool(value.get("confirmationRequiredForNewRecord", False)),
            candidate_disclosure_profile=str(value.get("candidateDisclosureProfile", "")),
            match_features=tuple(str(item) for item in value.get("matchFeatures", ())),  # type: ignore[union-attr]
        )


@dataclass(frozen=True, slots=True)
class IdentityPersonRecord:
    person_ref: str
    display_name: str
    authorization_scopes: tuple[str, ...]
    program_person_identifier: str | None = None
    household_identifier: str | None = None
    names: tuple[str, ...] = ()
    name_variants: tuple[str, ...] = ()
    sex: str | None = None
    date_of_birth: str | None = None
    estimated_age_years: int | None = None
    household_hint: str | None = None


@dataclass(frozen=True, slots=True)
class IdentityQuery:
    authorization_scopes: tuple[str, ...]
    offline: bool
    search_scope: OfflineSearchScope | None = None
    program_person_identifier: str | None = None
    household_identifier: str | None = None
    names: tuple[str, ...] = ()
    name_variants: tuple[str, ...] = ()
    sex: str | None = None
    date_of_birth: str | None = None
    estimated_age_years: int | None = None


@dataclass(frozen=True, slots=True)
class MinimalIdentityCandidate:
    candidate_person_ref: str
    display_name: str
    match_reasons: tuple[str, ...]
    approximate_age: str | None = None
    sex: str | None = None
    household_hint: str | None = None


@dataclass(frozen=True, slots=True)
class ConfirmNewProvenance:
    actor_ref: str
    asserted_at: str
    session_ref: str
    candidates_considered: tuple[str, ...]
    reason_code: str
    search_scope: OfflineSearchScope
    local_only_because_offline: bool
    note: str | None = None


@dataclass(frozen=True, slots=True)
class IdentityAdministrativeEvent:
    type: Literal["possible_duplicate_of", "duplicate_review_requested", "duplicate_review_resolved"]
    candidate_person_refs: tuple[str, ...]
    person_ref: str | None = None
    append_only: bool = True


@dataclass(frozen=True, slots=True)
class PersonIdentityResolutionRequest:
    duplicate_check_claimed: bool
    query: IdentityQuery
    people: tuple[IdentityPersonRecord, ...]
    provider: IdentityProviderConfig | None = None
    disposition: IdentityDisposition | None = None
    selected_person_ref: str | None = None
    new_person_ref: str | None = None
    confirm_new_provenance: ConfirmNewProvenance | None = None
    merge_requested: bool = False


@dataclass(frozen=True, slots=True)
class PersonIdentityResolutionResult:
    status: IdentityResolutionStatus
    candidates: tuple[MinimalIdentityCandidate, ...]
    administrative_events: tuple[IdentityAdministrativeEvent, ...]
    diagnostics: tuple[Diagnostic, ...]
    person_ref: str | None = None
    provenance: ConfirmNewProvenance | None = None
    search_scope: OfflineSearchScope | None = None


def _diagnostic(code: DiagnosticCode, message: str) -> Diagnostic:
    return Diagnostic(code=code, severity="error", message=message)


def _normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    return "".join(character for character in decomposed if character.isascii() and character.isalnum())


def _valid_instant(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return bool(value.strip())


def _compatible_age(query: IdentityQuery, person: IdentityPersonRecord) -> bool:
    if query.date_of_birth is not None and person.date_of_birth is not None:
        return query.date_of_birth == person.date_of_birth
    if query.estimated_age_years is None or person.estimated_age_years is None:
        return False
    return abs(query.estimated_age_years - person.estimated_age_years) <= 1


def _match_reasons(query: IdentityQuery, person: IdentityPersonRecord) -> tuple[str, ...]:
    if (
        query.program_person_identifier is not None
        and person.program_person_identifier is not None
        and query.program_person_identifier == person.program_person_identifier
    ):
        return ("exact_identifier",)
    query_names = {_normalized(item) for item in (*query.names, *query.name_variants) if _normalized(item)}
    person_names = {
        _normalized(item) for item in (person.display_name, *person.names, *person.name_variants) if _normalized(item)
    }
    same_name = bool(query_names.intersection(person_names))
    same_household = (
        query.household_identifier is not None and query.household_identifier == person.household_identifier
    )
    if not same_household or not same_name or not _compatible_age(query, person):
        return ()
    if query.sex is not None and person.sex is not None and query.sex != person.sex:
        return ()
    return (
        "same_household",
        "registered_name_match",
        "compatible_age",
        *(("compatible_sex",) if query.sex is not None and person.sex is not None else ()),
    )


def validate_identity_provider(provider: IdentityProviderConfig) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    if (
        not provider.id.strip()
        or not provider.version.strip()
        or provider.mode not in {"required", "external_master_index", "not_supported"}
        or provider.mode == "not_supported"
    ):
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.IDENTITY_PROVIDER_MISSING,
                "Active duplicate checking requires a versioned identity provider.",
            )
        )
    invalid_features = (
        not provider.match_features
        or len(set(provider.match_features)) != len(provider.match_features)
        or any(contains_clinical_vocabulary(feature) for feature in provider.match_features)
    )
    if (
        provider.scope != "authorized_catchment"
        or provider.candidate_disclosure_profile != "minimal-person-match"
        or not provider.confirmation_required_for_new_record
        or provider.offline_scope
        not in {"local_replica_only", "cached_authorized_index", "external_index_unavailable"}
        or invalid_features
    ):
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.IDENTITY_DISCLOSURE_INVALID,
                "Identity provider disclosure, authorization scope, or match-feature configuration is invalid.",
            )
        )
    return tuple(diagnostics)


def deterministic_identity_candidates(
    provider: IdentityProviderConfig,
    query: IdentityQuery,
    people: Sequence[IdentityPersonRecord],
) -> tuple[MinimalIdentityCandidate, ...]:
    if validate_identity_provider(provider):
        return ()
    candidates: list[MinimalIdentityCandidate] = []
    for person in people:
        if not set(person.authorization_scopes).intersection(query.authorization_scopes):
            continue
        reasons = _match_reasons(query, person)
        if not reasons:
            continue
        candidates.append(
            MinimalIdentityCandidate(
                candidate_person_ref=person.person_ref,
                display_name=person.display_name,
                match_reasons=reasons,
                approximate_age=(
                    None if person.estimated_age_years is None else f"{person.estimated_age_years} years"
                ),
                sex=person.sex,
                household_hint=person.household_hint,
            )
        )
    return tuple(sorted(candidates, key=lambda item: item.candidate_person_ref))


def resolve_person_identity(request: PersonIdentityResolutionRequest) -> PersonIdentityResolutionResult:
    diagnostics: list[Diagnostic] = []
    if request.merge_requested:
        return PersonIdentityResolutionResult(
            status="registration_blocked",
            candidates=(),
            administrative_events=(),
            diagnostics=(
                _diagnostic(
                    DiagnosticCode.IDENTITY_MERGE_FORBIDDEN,
                    "Automatic person merge is outside guideline IR.",
                ),
            ),
        )
    if request.duplicate_check_claimed and request.provider is None:
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.IDENTITY_PROVIDER_MISSING,
                "Duplicate checking was claimed without a provider.",
            )
        )
    if not request.query.authorization_scopes:
        diagnostics.append(
            _diagnostic(DiagnosticCode.IDENTITY_DISCLOSURE_INVALID, "Candidate search has no authorization scope.")
        )
    if request.query.offline and request.query.search_scope is None:
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.IDENTITY_OFFLINE_SCOPE_MISSING,
                "Offline identity search must declare its scope.",
            )
        )
    if request.provider is not None:
        diagnostics.extend(validate_identity_provider(request.provider))
    if diagnostics or request.provider is None:
        return PersonIdentityResolutionResult(
            status="registration_blocked", candidates=(), administrative_events=(), diagnostics=tuple(diagnostics)
        )

    candidates = deterministic_identity_candidates(request.provider, request.query, request.people)
    search_scope = request.query.search_scope or request.provider.offline_scope
    common = {
        "candidates": candidates,
        "diagnostics": tuple(diagnostics),
        "search_scope": search_scope,
    }
    if request.disposition == "select_existing":
        selected = next(
            (item for item in candidates if item.candidate_person_ref == request.selected_person_ref), None
        )
        return PersonIdentityResolutionResult(
            status="registration_blocked" if selected is None else "resolved_existing",
            person_ref=None if selected is None else selected.candidate_person_ref,
            administrative_events=(),
            **common,
        )
    if request.disposition == "confirm_new":
        provenance = request.confirm_new_provenance
        valid_provenance = (
            provenance is not None
            and bool(provenance.actor_ref.strip())
            and _valid_instant(provenance.asserted_at)
            and bool(provenance.session_ref.strip())
            and bool(provenance.reason_code.strip())
            and tuple(sorted(provenance.candidates_considered))
            == tuple(item.candidate_person_ref for item in candidates)
            and provenance.search_scope == search_scope
            and provenance.local_only_because_offline == request.query.offline
        )
        if not valid_provenance or not (request.new_person_ref or "").strip():
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.IDENTITY_PROVENANCE_MISSING,
                    "Confirmed-new registration requires append-only decision provenance and a person reference.",
                )
            )
            return PersonIdentityResolutionResult(
                status="registration_blocked",
                candidates=candidates,
                administrative_events=(),
                diagnostics=tuple(diagnostics),
                search_scope=search_scope,
            )
        person_ref = request.new_person_ref or ""
        events = (
            ()
            if not candidates
            else (
                IdentityAdministrativeEvent(
                    type="possible_duplicate_of",
                    person_ref=person_ref,
                    candidate_person_refs=tuple(item.candidate_person_ref for item in candidates),
                ),
            )
        )
        return PersonIdentityResolutionResult(
            status="created_new",
            person_ref=person_ref,
            provenance=provenance,
            administrative_events=events,
            **common,
        )
    if request.disposition == "escalate":
        event = IdentityAdministrativeEvent(
            type="duplicate_review_requested",
            candidate_person_refs=tuple(item.candidate_person_ref for item in candidates),
        )
        return PersonIdentityResolutionResult(
            status="registration_blocked", administrative_events=(event,), **common
        )
    if request.disposition == "defer_registration":
        return PersonIdentityResolutionResult(
            status="registration_deferred", administrative_events=(), **common
        )
    exact = tuple(item for item in candidates if "exact_identifier" in item.match_reasons)
    if len(exact) == 1:
        return PersonIdentityResolutionResult(
            status="resolved_existing",
            person_ref=exact[0].candidate_person_ref,
            administrative_events=(),
            **common,
        )
    return PersonIdentityResolutionResult(status="registration_deferred", administrative_events=(), **common)
