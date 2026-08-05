"""Canonical mutable-field policies, correction events, and pure conflict resolution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from functools import cmp_to_key
import json
from types import MappingProxyType
from typing import Literal, Mapping, Sequence

from .diagnostics import Diagnostic, DiagnosticCode


ConflictPolicyKind = Literal["append_correction", "field_merge", "flag_for_review", "immutable_after_creation"]
CANONICAL_ORDERING_RULES = (
    "explicit_supersession",
    "source_authority",
    "authorized_workflow",
    "platform_receipt",
    "stable_event_id",
)


@dataclass(frozen=True, slots=True)
class AuthorityClass:
    id: str
    rank: int


@dataclass(frozen=True, slots=True)
class RegisteredFieldConflictPolicy:
    field: str
    field_class: str
    conflict_policy: ConflictPolicyKind
    allowed_authority_classes: tuple[str, ...]
    same_field_conflict_fallback: ConflictPolicyKind | None = None
    append_only_clinical_evidence: bool = False


@dataclass(frozen=True, slots=True)
class ConflictPolicyRegistry:
    id: str
    version: str
    resolver: str
    ordering_rules: tuple[str, ...]
    authority_classes: tuple[AuthorityClass, ...]
    fields: tuple[RegisteredFieldConflictPolicy, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ConflictPolicyRegistry":
        authorities = tuple(
            AuthorityClass(id=str(item["id"]), rank=int(item["rank"]))
            for item in value.get("authorityClasses", ())  # type: ignore[union-attr]
        )
        fields = tuple(
            RegisteredFieldConflictPolicy(
                field=str(item["field"]),
                field_class=str(item["fieldClass"]),
                conflict_policy=str(item["conflictPolicy"]),  # type: ignore[arg-type]
                same_field_conflict_fallback=(
                    None
                    if item.get("sameFieldConflictFallback") is None
                    else str(item["sameFieldConflictFallback"])
                ),  # type: ignore[arg-type]
                allowed_authority_classes=tuple(str(entry) for entry in item.get("allowedAuthorityClasses", ())),
                append_only_clinical_evidence=bool(item.get("appendOnlyClinicalEvidence", False)),
            )
            for item in value.get("fields", ())  # type: ignore[union-attr]
        )
        return cls(
            id=str(value.get("id", "")),
            version=str(value.get("version", "")),
            resolver=str(value.get("resolver", "")),
            ordering_rules=tuple(str(item) for item in value.get("orderingRules", ())),  # type: ignore[union-attr]
            authority_classes=authorities,
            fields=fields,
        )


@dataclass(frozen=True, slots=True)
class CorrectionEvent:
    event_id: str
    person_ref: str
    field: str
    value: object
    asserted_at: str
    effective_at: str
    received_at: str
    actor_ref: str
    source_ref: str
    authority_class: str
    authorized_workflow: bool
    supersedes: str | None
    reason_code: str
    provenance_ref: str


@dataclass(frozen=True, slots=True)
class UnresolvedFieldConflict:
    person_ref: str
    field: str
    event_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class ConflictReviewObligation:
    id: str
    person_ref: str
    field: str
    event_ids: tuple[str, ...]
    execution: Literal["not_queued"] = "not_queued"


@dataclass(frozen=True, slots=True)
class MutableConflictResolution:
    all_assertions: tuple[CorrectionEvent, ...]
    projections: Mapping[str, Mapping[str, object]]
    unresolved_conflicts: tuple[UnresolvedFieldConflict, ...]
    review_obligations: tuple[ConflictReviewObligation, ...]
    diagnostics: tuple[Diagnostic, ...]
    ordering_explanation: tuple[str, ...]
    evidence: Literal["local_pure_resolver"] = "local_pure_resolver"


@dataclass(frozen=True, slots=True)
class CHTConflictFixture:
    winning_revision: CorrectionEvent
    losing_revisions: tuple[CorrectionEvent, ...]


@dataclass(frozen=True, slots=True)
class FHIRVersionConflictFixture:
    attempted_event: CorrectionEvent
    http_status: Literal[409, 412]


def _diagnostic(code: DiagnosticCode, message: str) -> Diagnostic:
    return Diagnostic(code=code, severity="error", message=message)


def _stable_event(event: CorrectionEvent) -> str:
    return json.dumps(asdict(event), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _instant(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (OSError, TypeError, ValueError):
        return float("-inf")


def _supersedes(left: CorrectionEvent, right: CorrectionEvent, by_id: Mapping[str, CorrectionEvent]) -> bool:
    if left.person_ref != right.person_ref:
        return False
    current = left.supersedes
    seen: set[str] = set()
    while current is not None and current not in seen:
        seen.add(current)
        ancestor = by_id.get(current)
        if ancestor is None or ancestor.person_ref != left.person_ref:
            return False
        if current == right.event_id:
            return True
        current = None if ancestor is None else ancestor.supersedes
    return False


def _compare_events(
    left: CorrectionEvent,
    right: CorrectionEvent,
    ranks: Mapping[str, int],
    by_id: Mapping[str, CorrectionEvent],
) -> int:
    if _supersedes(left, right, by_id):
        return 1
    if _supersedes(right, left, by_id):
        return -1
    authority = ranks.get(left.authority_class, -1) - ranks.get(right.authority_class, -1)
    if authority:
        return authority
    if left.authorized_workflow != right.authorized_workflow:
        return 1 if left.authorized_workflow else -1
    left_receipt = _instant(left.received_at)
    right_receipt = _instant(right.received_at)
    if left_receipt != right_receipt:
        return 1 if left_receipt > right_receipt else -1
    return (left.event_id > right.event_id) - (left.event_id < right.event_id)


def validate_conflict_policy_registry(registry: ConflictPolicyRegistry) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    authority_ids = tuple(authority.id for authority in registry.authority_classes)
    authorities = set(authority_ids)
    if (
        registry.resolver != "canonical.mutable-field-resolver@1.0.0"
        or not registry.id.strip()
        or not registry.version.strip()
        or len(authorities) != len(authority_ids)
        or any(not authority.id or authority.rank < 0 for authority in registry.authority_classes)
        or registry.ordering_rules != CANONICAL_ORDERING_RULES
    ):
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.CONFLICT_RESOLVER_INVALID,
                "Conflict policy references an unknown resolver.",
            )
        )
    if not registry.ordering_rules or (
        "device_time" in registry.ordering_rules
        and not {"source_authority", "explicit_supersession"}.intersection(registry.ordering_rules)
    ):
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.CONFLICT_DEVICE_TIME_AUTHORITY,
                "Device time cannot be the sole conflict authority.",
            )
        )
    seen_fields: set[str] = set()
    for field in registry.fields:
        if not field.field or field.field in seen_fields:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CONFLICT_RESOLVER_INVALID,
                    f"Mutable field policy '{field.field}' is blank or duplicated.",
                )
            )
        seen_fields.add(field.field)
        if field.append_only_clinical_evidence:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CONFLICT_CLINICAL_EVIDENCE_MUTABLE,
                    f"Append-only clinical evidence field '{field.field}' cannot use a mutable-field policy.",
                )
            )
        if (
            field.conflict_policy
            not in {"append_correction", "field_merge", "flag_for_review", "immutable_after_creation"}
            or not field.allowed_authority_classes
            or len(set(field.allowed_authority_classes)) != len(field.allowed_authority_classes)
            or any(authority not in authorities for authority in field.allowed_authority_classes)
            or (field.conflict_policy == "field_merge") != (field.same_field_conflict_fallback is not None)
        ):
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CONFLICT_RESOLVER_INVALID,
                    f"Field '{field.field}' references an unregistered authority class.",
                )
            )
    return tuple(diagnostics)


def _unresolved(
    person_ref: str, field: str, events: Sequence[CorrectionEvent], reason: str
) -> UnresolvedFieldConflict:
    return UnresolvedFieldConflict(
        person_ref=person_ref,
        field=field,
        event_ids=tuple(sorted(event.event_id for event in events)),
        reason=reason,
    )


def _obligation(conflict: UnresolvedFieldConflict) -> ConflictReviewObligation:
    return ConflictReviewObligation(
        id=f"review:{conflict.person_ref}:{conflict.field}:{'+'.join(conflict.event_ids)}",
        person_ref=conflict.person_ref,
        field=conflict.field,
        event_ids=conflict.event_ids,
    )


def resolve_mutable_field_conflicts(
    registry: ConflictPolicyRegistry, input_events: Sequence[CorrectionEvent]
) -> MutableConflictResolution:
    diagnostics = list(validate_conflict_policy_registry(registry))
    canonical_by_id: dict[str, set[str]] = {}
    unique_by_canonical: dict[tuple[str, str], CorrectionEvent] = {}
    for event in input_events:
        canonical = _stable_event(event)
        canonical_by_id.setdefault(event.event_id, set()).add(canonical)
        unique_by_canonical.setdefault((event.event_id, canonical), event)
    for event_id, variants in sorted(canonical_by_id.items()):
        if len(variants) > 1:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CONFLICT_ASSERTION_DROPPED,
                    f"Divergent assertions share event ID '{event_id}'; neither may be silently dropped.",
                )
            )
    all_assertions = tuple(
        sorted(unique_by_canonical.values(), key=lambda item: (item.event_id, _stable_event(item)))
    )
    by_id = {
        event_id: next(event for event in all_assertions if event.event_id == event_id)
        for event_id, variants in canonical_by_id.items()
        if len(variants) == 1
    }
    for event in all_assertions:
        target = None if event.supersedes is None else by_id.get(event.supersedes)
        if target is not None and target.person_ref != event.person_ref:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CONFLICT_RESOLVER_INVALID,
                    f"Event '{event.event_id}' cannot supersede an assertion for another person.",
                )
            )
    ranks = {authority.id: authority.rank for authority in registry.authority_classes}
    policies = {policy.field: policy for policy in registry.fields}
    grouped: dict[tuple[str, str], list[CorrectionEvent]] = {}
    for event in all_assertions:
        policy = policies.get(event.field)
        if policy is None:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CONFLICT_POLICY_MISSING,
                    f"Mutable field '{event.field}' has no registered conflict policy.",
                )
            )
            continue
        if policy.append_only_clinical_evidence:
            continue
        if event.authority_class not in policy.allowed_authority_classes or event.authority_class not in ranks:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CONFLICT_RESOLVER_INVALID,
                    f"Event '{event.event_id}' uses authority '{event.authority_class}' outside field policy.",
                )
            )
            continue
        grouped.setdefault((event.person_ref, event.field), []).append(event)

    projections: dict[str, dict[str, object]] = {}
    unresolved_conflicts: list[UnresolvedFieldConflict] = []
    for (person_ref, field), events in sorted(grouped.items()):
        policy = policies[field]
        missing_supersession = any(
            event.supersedes is not None
            and (
                event.supersedes not in by_id
                or by_id[event.supersedes].person_ref != event.person_ref
            )
            for event in events
        )
        distinct_values = {
            json.dumps(event.value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) for event in events
        }
        ordered = sorted(
            events,
            key=cmp_to_key(lambda left, right: _compare_events(left, right, ranks, by_id)),
        )
        effective_policy = (
            policy.same_field_conflict_fallback or "flag_for_review"
            if policy.conflict_policy == "field_merge"
            else policy.conflict_policy
        )
        needs_review = missing_supersession or (
            len(distinct_values) > 1 and effective_policy in {"flag_for_review", "immutable_after_creation"}
        )
        if needs_review:
            unresolved_conflicts.append(
                _unresolved(
                    person_ref,
                    field,
                    events,
                    "superseded event is missing"
                    if missing_supersession
                    else f"policy {effective_policy} requires review",
                )
            )
            continue
        projected = ordered[-1]
        projections.setdefault(person_ref, {})[field] = projected.value
        has_explicit_resolution = any(
            event.supersedes is not None and event.supersedes in by_id for event in events
        )
        if len(distinct_values) > 1 and not has_explicit_resolution:
            unresolved_conflicts.append(
                _unresolved(person_ref, field, events, "projection selected but concurrent assertions remain visible")
            )

    ordered_conflicts = tuple(sorted(unresolved_conflicts, key=lambda item: (item.person_ref, item.field)))
    frozen_projections = MappingProxyType(
        {
            person: MappingProxyType(dict(sorted(fields.items())))
            for person, fields in sorted(projections.items())
        }
    )
    return MutableConflictResolution(
        all_assertions=all_assertions,
        projections=frozen_projections,
        unresolved_conflicts=ordered_conflicts,
        review_obligations=tuple(_obligation(conflict) for conflict in ordered_conflicts),
        diagnostics=tuple(diagnostics),
        ordering_explanation=(
            "explicit supersession",
            "registered source authority",
            "authorized correction workflow",
            "platform receipt order",
            "stable event identifier",
            "asserted_at and effective_at do not establish authority",
        ),
    )


def correction_events_from_cht_conflict_fixture(fixture: CHTConflictFixture) -> tuple[CorrectionEvent, ...]:
    return tuple(sorted((fixture.winning_revision, *fixture.losing_revisions), key=lambda item: item.event_id))


def review_obligation_from_fhir_conflict_fixture(fixture: FHIRVersionConflictFixture) -> ConflictReviewObligation:
    return ConflictReviewObligation(
        id=f"review:fhir:{fixture.http_status}:{fixture.attempted_event.event_id}",
        person_ref=fixture.attempted_event.person_ref,
        field=fixture.attempted_event.field,
        event_ids=(fixture.attempted_event.event_id,),
    )
