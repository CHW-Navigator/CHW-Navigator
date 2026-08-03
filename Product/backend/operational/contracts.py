"""Fail-closed contracts for Prompts 8--10 operational intent.

The Gen 8 pipeline's ``clinical_logic.json`` is deliberately not extended
with people, facilities, delivery channels, or lifecycle state.  These
contracts keep those concerns in a separately versioned companion package.
They are standard-library only so the release gates can inspect them without
loading the model, database, or delivery stack.
"""

from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from typing import Any, Iterable


class OperationalValidationError(ValueError):
    """Raised when an operational artifact cannot safely proceed."""


ALLOWED_TOPOLOGY_RELATIONS = {
    "patient.assigned_worker",
    "patient.household",
    "patient.service_area",
    "patient.supervising_facility",
    "actor.supervisor",
    "patient.primary_caregiver",
    "eligible_referral_facility",
}

ALLOWED_EFFECT_KINDS = {
    "message",
    "referral_notification",
    "counter_referral_notification",
    "webhook",
}

TERMINAL_EFFECT_STATES = {
    "cancelled",
    "expired",
    "failed",
    "human_acknowledged",
    "referral_accepted",
    "counter_referral_completed",
}

FORBIDDEN_EFFECT_FIELDS = {
    "address",
    "phone",
    "recipient_id",
    "recipient_address",
    "recipient_phone",
    "url",
    "webhook_url",
    "credential",
    "credentials",
    "password",
    "token",
    "secret",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OperationalValidationError(f"{label} must be an object")
    return value


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OperationalValidationError(f"{label} must be a non-empty string")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise OperationalValidationError(f"{label} must be a list")
    return value


def _require_sha256(value: Any, label: str) -> str:
    """Require the exact content digest used by Gen 8 provenance sidecars."""
    digest = _require_string(value, label)
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
        raise OperationalValidationError(f"{label} must be a SHA-256 hex digest")
    return digest.lower()


def _parse_timestamp(value: Any, label: str) -> datetime:
    """Parse an offset-aware RFC 3339 timestamp without using local time."""
    text = _require_string(value, label)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise OperationalValidationError(f"{label} must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise OperationalValidationError(f"{label} must include a timezone offset")
    return parsed


def _require_source(candidate: dict[str, Any], label: str) -> None:
    source = _require_mapping(candidate.get("source"), f"{label}.source")
    for field in ("document_id", "page", "section", "quote"):
        _require_string(source.get(field), f"{label}.source.{field}")


def _candidate_signature(candidate: dict[str, Any]) -> tuple[Any, ...]:
    """Return the exact properties an approved registry entry must share."""
    for field in ("family", "operation", "resource", "backend"):
        _require_string(candidate.get(field), f"candidate.{field}")
    inputs = tuple(sorted(_require_list(candidate.get("input_types"), "candidate.input_types")))
    outputs = tuple(sorted(_require_list(candidate.get("output_types"), "candidate.output_types")))
    return (
        candidate["family"],
        candidate["operation"],
        candidate["resource"],
        candidate["backend"],
        inputs,
        outputs,
    )


def resolve_capability(
    candidate: dict[str, Any], registry_entries: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    """Resolve one capability only when there is one exact, approved match.

    An AI-produced candidate is evidence for what needs to be resolved; it
    never selects an entry.  Identifier order, confidence, and display name
    are intentionally absent from the matching rule.
    """
    candidate = _require_mapping(candidate, "candidate")
    candidate_id = _require_string(candidate.get("id"), "candidate.id")
    _require_source(candidate, "candidate")
    family, operation, resource, backend, inputs, outputs = _candidate_signature(candidate)

    if candidate.get("requires_human_review") and not candidate.get("review_approval"):
        return {
            "candidate_id": candidate_id,
            "status": "blocked",
            "reason": "human_review_required",
        }

    matches: list[dict[str, Any]] = []
    for raw_entry in registry_entries:
        entry = _require_mapping(raw_entry, "registry entry")
        if entry.get("status") != "active" or entry.get("approved") is not True:
            continue
        if (
            entry.get("family"),
            entry.get("operation"),
            entry.get("resource"),
        ) != (family, operation, resource):
            continue
        if backend not in _require_list(entry.get("backends"), "registry entry.backends"):
            continue
        if tuple(sorted(_require_list(entry.get("input_types"), "registry entry.input_types"))) != inputs:
            continue
        if tuple(sorted(_require_list(entry.get("output_types"), "registry entry.output_types"))) != outputs:
            continue
        matches.append(entry)

    if not matches:
        return {"candidate_id": candidate_id, "status": "blocked", "reason": "no_exact_match"}
    if len(matches) > 1:
        return {"candidate_id": candidate_id, "status": "blocked", "reason": "ambiguous_exact_match"}

    match = matches[0]
    return {
        "candidate_id": candidate_id,
        "status": "resolved",
        "entry_id": _require_string(match.get("id"), "registry entry.id"),
        "entry_version": _require_string(match.get("version"), "registry entry.version"),
    }


def validate_lifecycle_definition(definition: dict[str, Any]) -> None:
    """Validate replay safety and prove each state has an endpoint path."""
    definition = _require_mapping(definition, "lifecycle definition")
    for field in ("id", "version", "predicate_set_version", "dmn_version", "initial_state"):
        _require_string(definition.get(field), f"lifecycle definition.{field}")

    states = _require_list(definition.get("states"), "lifecycle definition.states")
    transitions = _require_list(definition.get("transitions"), "lifecycle definition.transitions")
    if not states:
        raise OperationalValidationError("lifecycle definition needs at least one state")

    state_map: dict[str, dict[str, Any]] = {}
    for raw_state in states:
        state = _require_mapping(raw_state, "lifecycle state")
        state_id = _require_string(state.get("id"), "lifecycle state.id")
        if state_id in state_map:
            raise OperationalValidationError(f"duplicate lifecycle state: {state_id}")
        if not isinstance(state.get("terminal"), bool):
            raise OperationalValidationError(f"lifecycle state {state_id} must declare terminal")
        if state.get("recovery") and not state["terminal"]:
            raise OperationalValidationError(f"recovery state {state_id} must be terminal")
        state_map[state_id] = state

    initial = definition["initial_state"]
    if initial not in state_map:
        raise OperationalValidationError("initial_state is not declared")

    edges: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw_transition in transitions:
        transition = _require_mapping(raw_transition, "lifecycle transition")
        from_state = _require_string(transition.get("from"), "lifecycle transition.from")
        to_state = _require_string(transition.get("to"), "lifecycle transition.to")
        event_type = _require_string(transition.get("event_type"), "lifecycle transition.event_type")
        if from_state not in state_map or to_state not in state_map:
            raise OperationalValidationError("lifecycle transition references an unknown state")
        if state_map[from_state]["terminal"]:
            raise OperationalValidationError(f"terminal state {from_state} cannot transition")
        if transition.get("requires_guard"):
            _require_string(transition.get("guard_id"), "lifecycle transition.guard_id")
        if state_map[to_state].get("recovery"):
            if transition.get("event_category") != "clinical" or not transition.get("requires_guard"):
                raise OperationalValidationError(
                    f"recovery transition {from_state}->{to_state} needs a clinical event and guard"
                )
            if event_type in {"timer", "task_expired", "silence", "sync_absent"}:
                raise OperationalValidationError("a nonclinical event cannot establish recovery")
        edges[from_state].append(transition)

    # Every declared state must be reachable from the versioned initial state.
    seen = {initial}
    pending = deque([initial])
    while pending:
        current = pending.popleft()
        for edge in edges[current]:
            target = edge["to"]
            if target not in seen:
                seen.add(target)
                pending.append(target)
    unreachable = sorted(set(state_map) - seen)
    if unreachable:
        raise OperationalValidationError(f"unreachable lifecycle states: {', '.join(unreachable)}")

    # Every reachable nonterminal state must lead to some terminal state.
    reverse: dict[str, set[str]] = defaultdict(set)
    for from_state, items in edges.items():
        for edge in items:
            reverse[edge["to"]].add(from_state)
    reaches_terminal = {state_id for state_id, state in state_map.items() if state["terminal"]}
    pending = deque(reaches_terminal)
    while pending:
        current = pending.popleft()
        for prior in reverse[current]:
            if prior not in reaches_terminal:
                reaches_terminal.add(prior)
                pending.append(prior)
    dead_ends = sorted(state for state in state_map if not state_map[state]["terminal"] and state not in reaches_terminal)
    if dead_ends:
        raise OperationalValidationError(f"nonterminal states without endpoint path: {', '.join(dead_ends)}")


def project_lifecycle(
    definition: dict[str, Any], events: Iterable[dict[str, Any]], episode_id: str
) -> dict[str, Any]:
    """Fold append-only events into state, quarantining unsafe events.

    Only identical duplicate event IDs are idempotent.  Conflicting variants,
    ordering collisions, stale guards, and invalid transitions are retained as
    quarantined evidence and never alter the materialized state.
    """
    validate_lifecycle_definition(definition)
    state_map = {state["id"]: state for state in definition["states"]}
    transitions: dict[tuple[str, str], dict[str, Any]] = {}
    for transition in definition["transitions"]:
        key = (transition["from"], transition["event_type"])
        if key in transitions:
            raise OperationalValidationError(f"ambiguous transition for {key[0]} / {key[1]}")
        transitions[key] = transition

    event_variants: dict[str, list[dict[str, Any]]] = defaultdict(list)
    quarantined: list[dict[str, str]] = []
    for raw_event in events:
        if not isinstance(raw_event, dict):
            quarantined.append({"event_id": "unknown", "reason": "malformed_event"})
            continue
        event = deepcopy(raw_event)
        event_id = event.get("id")
        if not isinstance(event_id, str) or not event_id.strip():
            quarantined.append({"event_id": "unknown", "reason": "malformed_event"})
            continue
        event_variants[event_id].append(deepcopy(event))

    unique: dict[str, dict[str, Any]] = {}
    for event_id, variants in event_variants.items():
        serialized_variants = {_canonical_json(variant) for variant in variants}
        if len(serialized_variants) == 1:
            unique[event_id] = variants[0]
        else:
            # Quarantine every variant, including the first arrival.  Keeping
            # a later equivalent variant would reintroduce arrival-order
            # dependence after a conflict has been observed.
            quarantined.extend(
                {"event_id": event_id, "reason": "conflicting_duplicate"}
                for _ in variants
            )

    by_sequence: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in unique.values():
        sequence = event.get("causal_sequence")
        if not isinstance(sequence, int) or sequence < 0:
            quarantined.append({"event_id": str(event["id"]), "reason": "invalid_causal_sequence"})
            continue
        by_sequence[sequence].append(event)

    # A shared causal sequence cannot be resolved with arrival order, timestamps,
    # or identifiers.  Quarantine every collision instead of allowing one bad
    # event to prevent deterministic replay of unrelated evidence.
    ordered: list[dict[str, Any]] = []
    for sequence in sorted(by_sequence):
        items = by_sequence[sequence]
        if len(items) > 1:
            quarantined.extend(
                {"event_id": str(item["id"]), "reason": "conflicting_causal_sequence"}
                for item in items
            )
            continue
        ordered.append(items[0])

    current_state = definition["initial_state"]
    applied: list[str] = []
    for event in ordered:
        event_id = str(event["id"])
        required_strings = ("episode_id", "event_type", "event_category", "predicate_set_version", "dmn_version")
        if any(not isinstance(event.get(field), str) or not event[field].strip() for field in required_strings):
            quarantined.append({"event_id": event_id, "reason": "malformed_event"})
            continue
        if event["event_category"] not in {"clinical", "timer", "external"}:
            quarantined.append({"event_id": event_id, "reason": "invalid_event_category"})
            continue
        try:
            _parse_timestamp(event.get("recorded_at"), "episode event.recorded_at")
            _parse_timestamp(event.get("occurred_at"), "episode event.occurred_at")
        except OperationalValidationError:
            quarantined.append({"event_id": event_id, "reason": "invalid_event_timestamp"})
            continue
        if event.get("episode_id") != episode_id:
            quarantined.append({"event_id": event_id, "reason": "foreign_episode"})
            continue
        if state_map[current_state]["terminal"]:
            quarantined.append({"event_id": event_id, "reason": "post_terminal"})
            continue
        if (
            event.get("predicate_set_version") != definition["predicate_set_version"]
            or event.get("dmn_version") != definition["dmn_version"]
        ):
            quarantined.append({"event_id": event_id, "reason": "stale_clinical_version"})
            continue
        transition = transitions.get((current_state, event.get("event_type")))
        if transition is None:
            quarantined.append({"event_id": event_id, "reason": "unsupported_transition"})
            continue
        next_state = transition["to"]
        if transition.get("requires_guard"):
            try:
                guard_id = _require_string(event.get("guard_id"), "episode event.guard_id")
                expected_guard_id = _require_string(transition.get("guard_id"), "lifecycle transition.guard_id")
                guard_evaluated_at = _parse_timestamp(
                    event.get("guard_evaluated_at"), "episode event.guard_evaluated_at"
                )
                recorded_at = _parse_timestamp(event.get("recorded_at"), "episode event.recorded_at")
            except OperationalValidationError:
                quarantined.append({"event_id": event_id, "reason": "invalid_guard_evidence"})
                continue
            if guard_id != expected_guard_id or guard_evaluated_at > recorded_at:
                quarantined.append({"event_id": event_id, "reason": "invalid_guard_evidence"})
                continue
        if state_map[next_state].get("recovery"):
            if (
                event.get("event_category") != "clinical"
                or event.get("guard_passed") is not True
                or event.get("guard_predicate_set_version") != definition["predicate_set_version"]
                or event.get("guard_dmn_version") != definition["dmn_version"]
            ):
                quarantined.append({"event_id": event_id, "reason": "invalid_recovery_evidence"})
                continue
        current_state = next_state
        applied.append(event_id)

    return {
        "episode_id": episode_id,
        "definition_id": definition["id"],
        "definition_version": definition["version"],
        "state": current_state,
        "applied_event_ids": applied,
        "quarantined_events": quarantined,
    }


def _validate_topology_requirements(requirements: list[Any]) -> None:
    for raw_requirement in requirements:
        requirement = _require_mapping(raw_requirement, "topology requirement")
        _require_string(requirement.get("id"), "topology requirement.id")
        relation = _require_string(requirement.get("relation"), "topology requirement.relation")
        if relation not in ALLOWED_TOPOLOGY_RELATIONS:
            raise OperationalValidationError(f"unsupported abstract topology relation: {relation}")
        for field in ("requester", "purpose", "topology_package", "topology_version"):
            _require_string(requirement.get(field), f"topology requirement.{field}")
        if "resolved_id" in requirement or "facility_id" in requirement or "actor_id" in requirement:
            raise OperationalValidationError("clinical operational requirements cannot name deployment identities")


def _find_forbidden_effect_field(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in FORBIDDEN_EFFECT_FIELDS:
                return str(key)
            found = _find_forbidden_effect_field(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_forbidden_effect_field(child)
            if found:
                return found
    return None


def _validate_external_effect_intents(intents: list[Any]) -> None:
    for raw_intent in intents:
        intent = _require_mapping(raw_intent, "external effect intent")
        forbidden = _find_forbidden_effect_field(intent)
        if forbidden:
            raise OperationalValidationError(f"external effect intent includes forbidden direct-delivery field: {forbidden}")
        for field in ("id", "purpose", "recipient_relation", "template_id", "adapter", "policy_version"):
            _require_string(intent.get(field), f"external effect intent.{field}")
        if intent.get("kind") not in ALLOWED_EFFECT_KINDS:
            raise OperationalValidationError("external effect intent has an unsupported kind")
        if intent["recipient_relation"] not in ALLOWED_TOPOLOGY_RELATIONS:
            raise OperationalValidationError("external effect intent must use an abstract topology relation")
        if intent.get("state", "planned") not in {"planned", "queued"}:
            raise OperationalValidationError("compile-time effect intents cannot claim provider or delivery evidence")
        _require_source(intent, "external effect intent")


def build_operational_package(
    requirements: dict[str, Any],
    registry_snapshot: dict[str, Any],
    *,
    clinical_logic_content_sha256: str,
) -> dict[str, Any]:
    """Validate and compile an operational companion package.

    This is a planning compiler.  It resolves no deployment identity, creates
    no task, and sends no external effect.  Those require the Prompt 9/10
    runtime layers and their deployment evidence.
    """
    requirements = _require_mapping(requirements, "operational requirements")
    registry_snapshot = _require_mapping(registry_snapshot, "registry snapshot")
    entries = _require_list(registry_snapshot.get("entries"), "registry snapshot.entries")
    _require_string(registry_snapshot.get("id"), "registry snapshot.id")
    _require_string(registry_snapshot.get("version"), "registry snapshot.version")
    clinical_logic_content_sha256 = _require_sha256(
        clinical_logic_content_sha256, "clinical_logic_content_sha256"
    )

    candidates = _require_list(requirements.get("capability_candidates", []), "capability_candidates")
    definitions = _require_list(requirements.get("lifecycle_definitions", []), "lifecycle_definitions")
    topology = _require_list(requirements.get("topology_requirements", []), "topology_requirements")
    effects = _require_list(requirements.get("external_effect_intents", []), "external_effect_intents")

    resolutions = [resolve_capability(candidate, entries) for candidate in candidates]
    candidate_ids = [resolution["candidate_id"] for resolution in resolutions]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise OperationalValidationError("capability candidate IDs must be unique")
    blocked = [resolution for resolution in resolutions if resolution["status"] != "resolved"]
    if blocked:
        reasons = ", ".join(f"{item['candidate_id']}:{item['reason']}" for item in blocked)
        raise OperationalValidationError(f"unresolved operational capabilities: {reasons}")

    definition_keys: set[tuple[str, str]] = set()
    for definition in definitions:
        validate_lifecycle_definition(_require_mapping(definition, "lifecycle definition"))
        key = (definition["id"], definition["version"])
        if key in definition_keys:
            raise OperationalValidationError("lifecycle definition IDs and versions must be unique")
        definition_keys.add(key)
    _validate_topology_requirements(topology)
    _validate_external_effect_intents(effects)

    version_lock = {
        "schema_version": "1.0",
        "clinical_logic_content_sha256": clinical_logic_content_sha256,
        "registry_snapshot": {
            "id": registry_snapshot["id"],
            "version": registry_snapshot["version"],
            "entries_digest": _digest(entries),
        },
        "capability_resolutions": [
            {
                "candidate_id": item["candidate_id"],
                "entry_id": item["entry_id"],
                "entry_version": item["entry_version"],
            }
            for item in sorted(resolutions, key=lambda item: item["candidate_id"])
        ],
        "lifecycle_definitions": [
            {
                "id": definition["id"],
                "version": definition["version"],
                "predicate_set_version": definition["predicate_set_version"],
                "dmn_version": definition["dmn_version"],
                "digest": _digest(definition),
            }
            for definition in sorted(definitions, key=lambda item: (item["id"], item["version"]))
        ],
    }

    package = {
        "schema_version": "1.0",
        "compile_status": "planned",
        "requirements_digest": _digest(requirements),
        "registry_snapshot": {
            "id": registry_snapshot["id"],
            "version": registry_snapshot["version"],
            "digest": _digest(entries),
        },
        "capability_resolutions": resolutions,
        "lifecycle_definitions": definitions,
        "version_lock": version_lock,
        "topology_requirements": topology,
        "external_effect_intents": effects,
    }
    return package
