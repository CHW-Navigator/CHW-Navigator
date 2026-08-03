"""Fail-closed Prompt 9 deployment-topology contracts.

Clinical packages supply only abstract relations.  This module validates a
separately versioned deployment package and resolves those relations against
effective-dated placement, assignment, capability, and access-policy data.
It produces reference decisions only: no identity provider, CHT, FHIR server,
device, or replication system is contacted here.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable

from .contracts import OperationalValidationError


TOPOLOGY_RELATIONS = {
    "contact.responsible-area",
    "patient.assigned-chw",
    "patient.supervising-entity",
    "referral.eligible-facilities",
}
TOPOLOGY_BACKENDS = {"cht", "fhir-r4"}
FORBIDDEN_NODE_FIELDS = {
    "id",
    "_id",
    "_rev",
    "platform_id",
    "platformid",
    "responsible_area_external_id",
    "responsibleareaexternalid",
}
FORBIDDEN_USER_ACCESS_FIELDS = {
    "permissions",
    "visibility",
    "replication_scope",
    "replicationscope",
}


def _diagnostic(
    code: str,
    message: str,
    *,
    path: str | None = None,
    related_ids: Iterable[str] = (),
    severity: str = "error",
) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if path:
        result["path"] = path
    ids = sorted({item for item in related_ids if isinstance(item, str) and item})
    if ids:
        result["related_ids"] = ids
    return result


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _parse_time(value: Any) -> datetime | None:
    text = _string(value)
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _valid_interval(item: dict[str, Any]) -> bool:
    start = _parse_time(item.get("active_from"))
    end = _parse_time(item.get("active_to")) if item.get("active_to") is not None else None
    return start is not None and (end is None or end > start)


def _active_at(item: dict[str, Any], at: datetime) -> bool:
    start = _parse_time(item.get("active_from"))
    end = _parse_time(item.get("active_to")) if item.get("active_to") is not None else None
    return start is not None and at >= start and (end is None or at < end)


def _overlaps(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_start = _parse_time(left.get("active_from"))
    right_start = _parse_time(right.get("active_from"))
    left_end = _parse_time(left.get("active_to")) if left.get("active_to") is not None else None
    right_end = _parse_time(right.get("active_to")) if right.get("active_to") is not None else None
    if left_start is None or right_start is None:
        return False
    return left_start < (right_end or datetime.max.replace(tzinfo=timezone.utc)) and right_start < (
        left_end or datetime.max.replace(tzinfo=timezone.utc)
    )


def _duplicates(values: Iterable[Any]) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        if isinstance(value, str):
            counts[value.strip()] += 1
    return sorted(value for value, count in counts.items() if value and count > 1)


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _indexes(package: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    schema = _mapping(package.get("schema"))
    types = {
        item["id"]: item
        for raw in _list(schema.get("contact_types"))
        if (item := _mapping(raw)).get("id") and isinstance(item.get("id"), str)
    }
    nodes = {
        item["external_id"]: item
        for raw in _list(package.get("nodes"))
        if (item := _mapping(raw)).get("external_id") and isinstance(item.get("external_id"), str)
    }
    return types, nodes


def _active_placements(package: dict[str, Any], at: datetime) -> list[dict[str, Any]]:
    return [
        item
        for raw in _list(package.get("placements"))
        if _active_at((item := _mapping(raw)), at)
    ]


def _parents(package: dict[str, Any], at: datetime) -> dict[str, str]:
    return {
        placement["child_external_id"]: placement["parent_external_id"]
        for placement in _active_placements(package, at)
        if _string(placement.get("child_external_id")) and _string(placement.get("parent_external_id"))
    }


def _ancestors(package: dict[str, Any], external_id: str, at: datetime) -> list[str]:
    parents = _parents(package, at)
    result: list[str] = []
    seen = {external_id}
    current = external_id
    while current in parents:
        parent = parents[current]
        if parent in seen:
            break
        seen.add(parent)
        result.append(parent)
        current = parent
    return result


def _descendants(package: dict[str, Any], external_id: str, at: datetime, max_depth: int | None = None) -> list[str]:
    children: dict[str, list[str]] = defaultdict(list)
    for placement in _active_placements(package, at):
        child = _string(placement.get("child_external_id"))
        parent = _string(placement.get("parent_external_id"))
        if child and parent:
            children[parent].append(child)
    result: list[str] = []
    queue: deque[tuple[str, int]] = deque([(external_id, 0)])
    seen = {external_id}
    while queue:
        current, depth = queue.popleft()
        if max_depth is not None and depth >= max_depth:
            continue
        for child in sorted(children.get(current, [])):
            if child in seen:
                continue
            seen.add(child)
            result.append(child)
            queue.append((child, depth + 1))
    return result


def _resolve_external_id(package: dict[str, Any], external_id: str) -> str | None:
    _, nodes = _indexes(package)
    if external_id in nodes:
        return external_id
    matches = [
        node_id
        for node_id, node in nodes.items()
        if external_id in _list(node.get("aliases"))
    ]
    return matches[0] if len(matches) == 1 else None


def _responsible_area(package: dict[str, Any], external_id: str, at: datetime) -> str | None:
    schema = _mapping(package.get("schema"))
    service_area_type = _string(schema.get("service_area_type_id"))
    types, nodes = _indexes(package)
    resolved = _resolve_external_id(package, external_id)
    if not resolved:
        return None
    for candidate in [resolved, *_ancestors(package, resolved, at)]:
        node = nodes.get(candidate)
        if node and _active_at(node, at) and node.get("contact_type") == service_area_type:
            return candidate
    return None


def validate_topology_package(
    package: dict[str, Any],
    *,
    at: str | None = None,
    deployment: bool = False,
    previous_schema: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return all safe-to-report Prompt 9 topology diagnostics.

    This validator never assumes a malformed input can be dereferenced.  It
    returns diagnostics for bad data so callers can present actionable review
    evidence instead of masking it with an exception.
    """
    diagnostics: list[dict[str, Any]] = []
    if not isinstance(package, dict):
        return [_diagnostic("H-ID", "Topology package must be an object")]

    evaluation_time = _parse_time(at or package.get("generated_at"))
    if evaluation_time is None:
        diagnostics.append(_diagnostic("H-EFFECTIVE", "Package generated_at must be an RFC 3339 timestamp", path="generated_at"))
        evaluation_time = datetime(1970, 1, 1, tzinfo=timezone.utc)

    for field in ("id", "version", "snapshot_id"):
        if not _string(package.get(field)):
            diagnostics.append(_diagnostic("H-ID", f"Topology package {field} is required", path=field))

    schema = _mapping(package.get("schema"))
    types, nodes = _indexes(package)
    service_area_type = _string(schema.get("service_area_type_id"))
    service_area_definition = types.get(service_area_type or "")
    if not service_area_definition or service_area_definition.get("kind") != "place" or service_area_definition.get("semantic") != "service-area":
        diagnostics.append(_diagnostic("H-TREE", "service_area_type_id must identify a place service-area type", path="schema.service_area_type_id"))

    contact_types = [_mapping(item) for item in _list(schema.get("contact_types"))]
    for identifier in _duplicates(item.get("id") for item in contact_types):
        diagnostics.append(_diagnostic("H-ID", f"Duplicate contact type ID {identifier}", path="schema.contact_types", related_ids=[identifier]))
    for index, contact_type in enumerate(contact_types):
        identifier = _string(contact_type.get("id"))
        if not identifier or identifier != contact_type.get("id"):
            diagnostics.append(_diagnostic("H-ID", "Contact type IDs must be non-empty and trimmed", path=f"schema.contact_types[{index}].id"))
            continue
        if contact_type.get("kind") not in {"place", "person"}:
            diagnostics.append(_diagnostic("H-TREE", f"Contact type {identifier} has invalid kind", path=f"schema.contact_types[{index}].kind", related_ids=[identifier]))
        for parent_type in _list(contact_type.get("allowed_parents")):
            if parent_type not in types:
                diagnostics.append(_diagnostic("H-TREE", f"Contact type {identifier} allows unknown parent type {parent_type}", path=f"schema.contact_types[{index}]", related_ids=[identifier, str(parent_type)]))

    raw_nodes = [_mapping(item) for item in _list(package.get("nodes"))]
    for identifier in _duplicates(item.get("external_id") for item in raw_nodes):
        diagnostics.append(_diagnostic("H-ID", f"Duplicate external ID {identifier}", path="nodes", related_ids=[identifier]))
    aliases: dict[str, list[str]] = defaultdict(list)
    for index, node in enumerate(raw_nodes):
        external_id = _string(node.get("external_id"))
        if not external_id or external_id != node.get("external_id"):
            diagnostics.append(_diagnostic("H-ID", "Node external_id must be non-empty and trimmed", path=f"nodes[{index}].external_id"))
            continue
        if node.get("contact_type") not in types:
            diagnostics.append(_diagnostic("H-TREE", f"Node {external_id} has an unknown contact type", path=f"nodes[{index}].contact_type", related_ids=[external_id]))
        if not _valid_interval(node):
            diagnostics.append(_diagnostic("H-EFFECTIVE", f"Node {external_id} has an invalid effective interval", path=f"nodes[{index}]", related_ids=[external_id]))
        for field in node:
            normalized = field.lower().replace("-", "_")
            if normalized in FORBIDDEN_NODE_FIELDS:
                code = "H-RESP" if "responsible" in normalized else "H-ID"
                diagnostics.append(_diagnostic(code, f"Node {external_id} contains forbidden deployment field {field}", path=f"nodes[{index}].{field}", related_ids=[external_id]))
        for alias in _list(node.get("aliases")):
            if not isinstance(alias, str) or not alias.strip() or alias != alias.strip():
                diagnostics.append(_diagnostic("H-ID", f"Node {external_id} has an invalid alias", path=f"nodes[{index}].aliases", related_ids=[external_id]))
            elif alias:
                aliases[alias].append(external_id)
    for alias, owners in aliases.items():
        if len(owners) > 1 or alias in nodes:
            diagnostics.append(_diagnostic("H-ID", f"Alias {alias} is ambiguous or collides with an external ID", path="nodes.aliases", related_ids=[alias, *owners]))

    placements = [_mapping(item) for item in _list(package.get("placements"))]
    for identifier in _duplicates(item.get("id") for item in placements):
        diagnostics.append(_diagnostic("H-ID", f"Duplicate placement ID {identifier}", path="placements", related_ids=[identifier]))
    placements_by_child: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, placement in enumerate(placements):
        placement_id = _string(placement.get("id")) or f"placements[{index}]"
        child_id = _string(placement.get("child_external_id"))
        parent_id = _string(placement.get("parent_external_id"))
        if not child_id or not parent_id or child_id not in nodes or parent_id not in nodes:
            diagnostics.append(_diagnostic("H-TREE", f"Placement {placement_id} references an unknown child or parent", path=f"placements[{index}]", related_ids=[placement_id, child_id or "", parent_id or ""]))
        elif child_id == parent_id:
            diagnostics.append(_diagnostic("H-TREE", f"Placement {placement_id} cannot self-parent", path=f"placements[{index}]", related_ids=[placement_id]))
        else:
            child_type = types.get(str(nodes[child_id].get("contact_type")))
            if child_type and parent_id:
                parent_type = nodes[parent_id].get("contact_type")
                if parent_type not in _list(child_type.get("allowed_parents")):
                    diagnostics.append(_diagnostic("H-TREE", f"Placement {placement_id} uses a disallowed parent type", path=f"placements[{index}]", related_ids=[child_id, parent_id]))
            placements_by_child[child_id].append(placement)
        if not _valid_interval(placement):
            diagnostics.append(_diagnostic("H-EFFECTIVE", f"Placement {placement_id} has an invalid effective interval", path=f"placements[{index}]", related_ids=[placement_id]))
    for child_id, child_placements in placements_by_child.items():
        for left_index, left in enumerate(child_placements):
            for right in child_placements[left_index + 1 :]:
                if _overlaps(left, right):
                    diagnostics.append(_diagnostic("H-RESP", f"Contact {child_id} has overlapping parent placements", related_ids=[child_id, str(left.get("id", "")), str(right.get("id", ""))]))

    # Check the tree at every effective-date boundary, not only the package
    # generation time.  A future transfer must not introduce a later cycle or
    # a second parent merely because the current snapshot looks sound.
    validation_times = {evaluation_time}
    for item in [*raw_nodes, *placements]:
        start = _parse_time(item.get("active_from"))
        end = _parse_time(item.get("active_to")) if item.get("active_to") is not None else None
        if start:
            validation_times.add(start)
        if end:
            validation_times.add(end)
    for check_time in sorted(validation_times):
        active_nodes = {node_id for node_id, node in nodes.items() if _active_at(node, check_time)}
        parents = _parents(package, check_time)
        for child_id, parent_id in parents.items():
            if child_id not in active_nodes or parent_id not in active_nodes:
                diagnostics.append(_diagnostic("H-TREE", "An active placement references an inactive node", related_ids=[child_id, parent_id]))
        for node_id in active_nodes:
            node_type = types.get(str(nodes[node_id].get("contact_type")))
            if not node_type:
                continue
            permits_parent = bool(_list(node_type.get("allowed_parents")))
            if permits_parent and node_id not in parents:
                diagnostics.append(_diagnostic("H-TREE", f"Non-root node {node_id} has no active parent", related_ids=[node_id]))
            if not permits_parent and node_id in parents:
                diagnostics.append(_diagnostic("H-TREE", f"Root-type node {node_id} has an active parent", related_ids=[node_id]))
        for node_id in active_nodes:
            seen: set[str] = set()
            current = node_id
            while current in parents:
                if current in seen:
                    diagnostics.append(_diagnostic("H-TREE", "Active topology contains a cycle", related_ids=[*seen, current]))
                    break
                seen.add(current)
                current = parents[current]

    assignments = [_mapping(item) for item in _list(package.get("assignments"))]
    for identifier in _duplicates(item.get("id") for item in assignments):
        diagnostics.append(_diagnostic("H-ID", f"Duplicate assignment ID {identifier}", path="assignments", related_ids=[identifier]))
    assignment_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for index, assignment in enumerate(assignments):
        assignment_id = _string(assignment.get("id")) or f"assignments[{index}]"
        area = _string(assignment.get("service_area_external_id"))
        assignee = _string(assignment.get("assignee_external_id"))
        relation = assignment.get("relation")
        if not area or area not in nodes or nodes[area].get("contact_type") != service_area_type:
            diagnostics.append(_diagnostic("H-ASSIGN", f"Assignment {assignment_id} must reference a service area", path=f"assignments[{index}]", related_ids=[assignment_id, area or ""]))
        if not assignee or assignee not in nodes:
            diagnostics.append(_diagnostic("H-ASSIGN", f"Assignment {assignment_id} has an unknown assignee", path=f"assignments[{index}]", related_ids=[assignment_id, assignee or ""]))
        elif relation == "serves" and types.get(str(nodes[assignee].get("contact_type")), {}).get("kind") != "person":
            diagnostics.append(_diagnostic("H-ASSIGN", f"serves assignment {assignment_id} must name a person", path=f"assignments[{index}]", related_ids=[assignment_id]))
        if relation not in {"serves", "supervises"}:
            diagnostics.append(_diagnostic("H-ASSIGN", f"Assignment {assignment_id} has an unsupported relation", path=f"assignments[{index}].relation", related_ids=[assignment_id]))
        if not _string(assignment.get("approved_by")):
            diagnostics.append(_diagnostic("H-ASSIGN", f"Assignment {assignment_id} lacks approval", path=f"assignments[{index}].approved_by", related_ids=[assignment_id]))
        if not _valid_interval(assignment):
            diagnostics.append(_diagnostic("H-EFFECTIVE", f"Assignment {assignment_id} has an invalid effective interval", path=f"assignments[{index}]", related_ids=[assignment_id]))
        if area and isinstance(relation, str):
            assignment_groups[(area, relation)].append(assignment)
    for (_, _), group in assignment_groups.items():
        for left_index, left in enumerate(group):
            for right in group[left_index + 1 :]:
                if _overlaps(left, right):
                    if left.get("coverage") is not True or right.get("coverage") is not True:
                        diagnostics.append(_diagnostic("H-EFFECTIVE", "Overlapping assignments must explicitly declare coverage", related_ids=[str(left.get("id", "")), str(right.get("id", ""))]))
                    if left.get("primary") is True and right.get("primary") is True:
                        diagnostics.append(_diagnostic("H-EFFECTIVE", "Overlapping assignments may have at most one primary", related_ids=[str(left.get("id", "")), str(right.get("id", ""))]))
        active_group = [item for item in group if _active_at(item, evaluation_time)]
        if len(active_group) > 1 and sum(item.get("primary") is True for item in active_group) != 1:
            diagnostics.append(_diagnostic("H-RESOLVE", "Concurrent assignments require exactly one primary for singular resolution", related_ids=[str(item.get("id", "")) for item in active_group], severity="error" if deployment else "warning"))

    vocabulary = _mapping(package.get("capability_vocabulary"))
    capability_codes = [item for item in _list(vocabulary.get("codes")) if isinstance(item, str)]
    for code in _duplicates(capability_codes):
        diagnostics.append(_diagnostic("H-CAP", f"Duplicate capability code {code}", path="capability_vocabulary.codes", related_ids=[code]))
    capability_set = set(capability_codes)
    capabilities = [_mapping(item) for item in _list(package.get("facility_capabilities"))]
    for index, capability in enumerate(capabilities):
        facility = _string(capability.get("facility_external_id"))
        code = _string(capability.get("capability_code"))
        facility_type = types.get(str(nodes.get(facility, {}).get("contact_type", "")))
        if not facility or facility_type is None or facility_type.get("semantic") != "facility" or facility_type.get("capabilities") is not True:
            diagnostics.append(_diagnostic("H-CAP", "Facility capability must reference a capability-bearing facility", path=f"facility_capabilities[{index}]", related_ids=[facility or ""]))
        if not code or code not in capability_set:
            diagnostics.append(_diagnostic("H-CAP", f"Unknown capability code {code or ''}", path=f"facility_capabilities[{index}].capability_code", related_ids=[code or ""]))
        if not _valid_interval(capability):
            diagnostics.append(_diagnostic("H-EFFECTIVE", "Facility capability has an invalid effective interval", path=f"facility_capabilities[{index}]"))
    for code in capability_set:
        if not any(item.get("capability_code") == code and _active_at(item, evaluation_time) for item in capabilities):
            diagnostics.append(_diagnostic("H-CAP", f"Capability {code} has no active implementing facility", related_ids=[code], severity="error" if deployment else "warning"))

    for index, cross_reference in enumerate(_mapping(item) for item in _list(package.get("cross_references"))):
        source = _string(cross_reference.get("from_external_id"))
        target = _string(cross_reference.get("to_external_id"))
        relation = str(cross_reference.get("relation", ""))
        if not source or not target or source not in nodes or target not in nodes:
            diagnostics.append(_diagnostic("H-REF", "Cross-reference has an unknown endpoint", path=f"cross_references[{index}]"))
        if any(token in relation.lower() for token in ("parent", "contain", "responsib")):
            diagnostics.append(_diagnostic("H-REF", "Cross-reference cannot create a parent or responsibility relation", path=f"cross_references[{index}].relation"))
        if not _valid_interval(cross_reference):
            diagnostics.append(_diagnostic("H-EFFECTIVE", "Cross-reference has an invalid effective interval", path=f"cross_references[{index}]"))

    access_policy = _mapping(package.get("access_policy"))
    if access_policy.get("default_deny") is not True:
        diagnostics.append(_diagnostic("H-ACCESS", "Access policy must default deny", path="access_policy.default_deny"))
    roles = [_mapping(item) for item in _list(access_policy.get("roles"))]
    role_index = {role["role"]: role for role in roles if isinstance(role.get("role"), str)}
    for role in _duplicates(item.get("role") for item in roles):
        diagnostics.append(_diagnostic("H-ACCESS", f"Duplicate access role {role}", path="access_policy.roles", related_ids=[role]))
    for index, role in enumerate(roles):
        if role.get("placement_scope") not in {"assigned-subtree", "assigned-service-area"}:
            diagnostics.append(_diagnostic("H-ACCESS", "Role has an invalid placement scope", path=f"access_policy.roles[{index}].placement_scope"))
        for contact_type in _list(role.get("allowed_contact_types")):
            if contact_type not in types:
                diagnostics.append(_diagnostic("H-ACCESS", f"Role {role.get('role', '')} permits an unknown contact type", path=f"access_policy.roles[{index}]", related_ids=[str(contact_type)]))
        max_depth = role.get("max_descendant_depth")
        if max_depth is not None and (not isinstance(max_depth, int) or max_depth < 0):
            diagnostics.append(_diagnostic("H-ACCESS", "Role max_descendant_depth must be a non-negative integer", path=f"access_policy.roles[{index}].max_descendant_depth"))
    for index, user in enumerate(_mapping(item) for item in _list(package.get("users"))):
        person = _string(user.get("person_external_id"))
        if not person or person not in nodes or types.get(str(nodes[person].get("contact_type")), {}).get("kind") != "person":
            diagnostics.append(_diagnostic("H-ACCESS", f"User {user.get('username', index)} must reference a person", path=f"users[{index}].person_external_id"))
        if user.get("role") not in role_index:
            diagnostics.append(_diagnostic("H-ACCESS", f"User {user.get('username', index)} has an unknown role", path=f"users[{index}].role"))
        assigned_places = _list(user.get("assigned_place_external_ids"))
        if not assigned_places:
            diagnostics.append(_diagnostic("H-ACCESS", f"User {user.get('username', index)} needs at least one assigned place", path=f"users[{index}].assigned_place_external_ids"))
        for assigned in assigned_places:
            node = nodes.get(assigned) if isinstance(assigned, str) else None
            if node is None or types.get(str(node.get("contact_type")), {}).get("kind") != "place":
                diagnostics.append(_diagnostic("H-ACCESS", f"User {user.get('username', index)} has an invalid assigned place", path=f"users[{index}].assigned_place_external_ids"))
        if not _valid_interval(user):
            diagnostics.append(_diagnostic("H-EFFECTIVE", f"User {user.get('username', index)} has an invalid effective interval", path=f"users[{index}]"))
        for field in user:
            if field.lower().replace("-", "_") in FORBIDDEN_USER_ACCESS_FIELDS:
                diagnostics.append(_diagnostic("H-ACCESS", f"User {user.get('username', index)} has a forbidden per-user access override", path=f"users[{index}].{field}"))

    relation_rules = [_mapping(item) for item in _list(package.get("relation_rules"))]
    for relation in _duplicates(item.get("relation") for item in relation_rules):
        diagnostics.append(_diagnostic("H-RESOLVE", f"Duplicate relation rule {relation}", path="relation_rules", related_ids=[relation]))
    rule_relations = {item.get("relation") for item in relation_rules}
    for relation in sorted(TOPOLOGY_RELATIONS - rule_relations):
        diagnostics.append(_diagnostic("H-RESOLVE", f"Required abstract relation {relation} is not bound", path="relation_rules", related_ids=[relation]))
    for index, rule in enumerate(relation_rules):
        if rule.get("relation") not in TOPOLOGY_RELATIONS:
            diagnostics.append(_diagnostic("H-RESOLVE", "Unsupported abstract relation", path=f"relation_rules[{index}].relation"))
        if rule.get("cardinality") not in {"one", "collection"}:
            diagnostics.append(_diagnostic("H-RESOLVE", "Relation rule has invalid cardinality", path=f"relation_rules[{index}].cardinality"))
        if not set(_list(rule.get("supported_backends"))) or not set(_list(rule.get("supported_backends"))).issubset(TOPOLOGY_BACKENDS):
            diagnostics.append(_diagnostic("H-RESOLVE", "Relation rule must name one or more supported backends", path=f"relation_rules[{index}].supported_backends"))

    for area_id, node in nodes.items():
        if node.get("contact_type") != service_area_type or not _active_at(node, evaluation_time):
            continue
        populated = bool(_descendants(package, area_id, evaluation_time))
        active_servers = [
            _mapping(item)
            for item in assignments
            if item.get("service_area_external_id") == area_id
            and item.get("relation") == "serves"
            and _active_at(item, evaluation_time)
        ]
        if populated and not active_servers:
            diagnostics.append(_diagnostic("H-UNASSIGNED", f"Populated service area {area_id} has no current serves assignment", related_ids=[area_id], severity="error" if deployment else "warning"))

    if previous_schema:
        old_schema = _mapping(previous_schema)
        prior_ids = set(_list(old_schema.get("protected_type_ids"))) or {
            item.get("id") for item in _list(old_schema.get("contact_types")) if isinstance(_mapping(item).get("id"), str)
        }
        migrations = {
            item.get("from"): item.get("to")
            for item in _list(schema.get("type_migrations"))
            if isinstance(_mapping(item).get("from"), str) and isinstance(_mapping(item).get("to"), str)
        }
        for prior in prior_ids:
            if prior not in types and prior not in migrations:
                diagnostics.append(_diagnostic("H-MIGRATE", f"Protected type {prior} was removed without an approved migration", path="schema.type_migrations", related_ids=[prior]))
            elif prior in migrations and migrations[prior] not in types:
                diagnostics.append(_diagnostic("H-MIGRATE", f"Migration target {migrations[prior]} is not a current contact type", path="schema.type_migrations", related_ids=[prior, str(migrations[prior])]))

    return sorted(diagnostics, key=lambda item: (item["code"], item["message"], item.get("path", "")))


def assert_topology_valid(package: dict[str, Any], **options: Any) -> list[dict[str, Any]]:
    diagnostics = validate_topology_package(package, **options)
    errors = [item for item in diagnostics if item["severity"] == "error"]
    if errors:
        codes = ", ".join(sorted({item["code"] for item in errors}))
        raise OperationalValidationError(f"invalid topology package: {codes}")
    return diagnostics


def validate_topology_requirements_against_package(
    requirements: Iterable[dict[str, Any]], package: dict[str, Any]
) -> None:
    """Bind typed clinical requirements to topology rules, never to identities."""
    assert_topology_valid(package, deployment=True)
    rules = {
        item.get("relation"): item
        for item in (_mapping(raw) for raw in _list(package.get("relation_rules")))
        if isinstance(item.get("relation"), str)
    }
    vocabulary = set(_list(_mapping(package.get("capability_vocabulary")).get("codes")))
    for raw_requirement in requirements:
        requirement = _mapping(raw_requirement)
        identifier = _string(requirement.get("id")) or "unknown"
        relation = requirement.get("relation")
        rule = rules.get(relation)
        if not rule:
            raise OperationalValidationError(
                f"topology requirement {identifier} has no approved runtime relation rule"
            )
        cardinality = requirement.get("cardinality")
        if cardinality is not None and cardinality != rule.get("cardinality"):
            raise OperationalValidationError(
                f"topology requirement {identifier} conflicts with the relation cardinality"
            )
        if "topology_package" in requirement and requirement.get("topology_package") != package.get("id"):
            raise OperationalValidationError(
                f"topology requirement {identifier} pins a different topology package"
            )
        if "topology_version" in requirement and requirement.get("topology_version") != package.get("version"):
            raise OperationalValidationError(
                f"topology requirement {identifier} pins a different topology version"
            )
        required_codes = _list(requirement.get("required_capability_codes"))
        unknown = sorted(set(required_codes) - vocabulary)
        if unknown:
            raise OperationalValidationError(
                f"topology requirement {identifier} names unknown capability codes: {', '.join(unknown)}"
            )


def build_topology_lock(package: dict[str, Any], *, resolver_version: str = "gen8.operational.topology@1.0") -> dict[str, Any]:
    """Produce the exact topology/configuration lock consumed by deployment code."""
    assert_topology_valid(package, deployment=True)
    return {
        "schema_version": "1.0",
        "resolver_version": resolver_version,
        "topology_package": {
            "id": package["id"],
            "version": package["version"],
            "snapshot_id": package["snapshot_id"],
            "content_digest": _canonical_digest(package),
            "schema_digest": _canonical_digest(package["schema"]),
            "access_policy_digest": _canonical_digest(package["access_policy"]),
            "capability_vocabulary_digest": _canonical_digest(package["capability_vocabulary"]),
        },
    }


def _resolution(
    package: dict[str, Any],
    request: dict[str, Any],
    status: str,
    matches: Iterable[str],
    *,
    reason: str | None = None,
    responsible_area_external_id: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "relation": request.get("relation"),
        "status": status,
        "cardinality": request.get("cardinality"),
        "matches": sorted(set(matches)),
        "topology_package": f"{package.get('id')}@{package.get('version')}",
        "snapshot_id": package.get("snapshot_id"),
        "evaluated_at": request.get("at"),
    }
    if reason:
        result["reason"] = reason
    if responsible_area_external_id:
        result["responsible_area_external_id"] = responsible_area_external_id
    return result


def _apply_cardinality(
    package: dict[str, Any],
    request: dict[str, Any],
    matches: Iterable[str],
    *,
    assignments: Iterable[dict[str, Any]] = (),
    responsible_area_external_id: str | None = None,
) -> dict[str, Any]:
    unique = sorted(set(matches))
    if not unique:
        return _resolution(package, request, "unassigned", (), reason="No current match for relation", responsible_area_external_id=responsible_area_external_id)
    if request["cardinality"] == "collection" or len(unique) == 1:
        return _resolution(package, request, "resolved", unique, responsible_area_external_id=responsible_area_external_id)
    primary_ids = sorted({str(item.get("assignee_external_id")) for item in assignments if item.get("primary") is True})
    if len(primary_ids) == 1:
        return _resolution(package, request, "resolved", primary_ids, responsible_area_external_id=responsible_area_external_id)
    return _resolution(package, request, "ambiguous", unique, reason="Multiple current matches and no unique primary", responsible_area_external_id=responsible_area_external_id)


def resolve_topology_relation(package: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    """Resolve an approved abstract relation without making a deployment call."""
    request = _mapping(request)
    invalid = [item for item in validate_topology_package(package) if item["severity"] == "error"]
    if invalid:
        return _resolution(package, request, "blocked", (), reason="Topology package is invalid")
    at = _parse_time(request.get("at"))
    relation = request.get("relation")
    cardinality = request.get("cardinality")
    backend = request.get("target_backend")
    if at is None or relation not in TOPOLOGY_RELATIONS or cardinality not in {"one", "collection"} or backend not in TOPOLOGY_BACKENDS:
        return _resolution(package, request, "blocked", (), reason="Relation request is malformed")
    rules = {_mapping(item).get("relation"): _mapping(item) for item in _list(package.get("relation_rules"))}
    rule = rules.get(relation)
    if not rule:
        return _resolution(package, request, "unsupported", (), reason="No relation rule is registered")
    if rule.get("cardinality") != cardinality:
        return _resolution(package, request, "blocked", (), reason="Requested cardinality conflicts with the relation rule")
    if backend not in _list(rule.get("supported_backends")):
        return _resolution(package, request, "unsupported", (), reason=f"Relation is not supported by {backend}")

    types, nodes = _indexes(package)
    if relation == "referral.eligible-facilities":
        required = sorted(set(item for item in _list(request.get("required_capability_codes")) if isinstance(item, str) and item))
        known = set(_list(_mapping(package.get("capability_vocabulary")).get("codes")))
        if not required:
            return _resolution(package, request, "blocked", (), reason="Referral resolution requires at least one capability code")
        unknown = sorted(set(required) - known)
        if unknown:
            return _resolution(package, request, "blocked", (), reason=f"Unknown required capability codes: {', '.join(unknown)}")
        capabilities = [_mapping(item) for item in _list(package.get("facility_capabilities"))]
        facilities = [
            node_id
            for node_id, node in nodes.items()
            if _active_at(node, at)
            and types.get(str(node.get("contact_type")), {}).get("semantic") == "facility"
            and all(
                any(capability.get("facility_external_id") == node_id and capability.get("capability_code") == code and _active_at(capability, at) for capability in capabilities)
                for code in required
            )
        ]
        return _apply_cardinality(package, request, facilities)

    subject = request.get("subject_external_id")
    resolved_subject = _resolve_external_id(package, subject) if isinstance(subject, str) else None
    if not resolved_subject or resolved_subject not in nodes or not _active_at(nodes[resolved_subject], at):
        return _resolution(package, request, "not-found", (), reason="Subject is unknown or inactive")
    area = _responsible_area(package, resolved_subject, at)
    if not area:
        return _resolution(package, request, "unassigned", (), reason="Subject has no responsible service area")
    if relation == "contact.responsible-area":
        return _apply_cardinality(package, request, [area], responsible_area_external_id=area)
    assignment_relation = "serves" if relation == "patient.assigned-chw" else "supervises"
    assignments = [
        _mapping(item)
        for item in _list(package.get("assignments"))
        if item.get("service_area_external_id") == area
        and item.get("relation") == assignment_relation
        and _active_at(item, at)
        and item.get("assignee_external_id") in nodes
        and _active_at(nodes[item["assignee_external_id"]], at)
    ]
    return _apply_cardinality(
        package,
        request,
        (str(item["assignee_external_id"]) for item in assignments),
        assignments=assignments,
        responsible_area_external_id=area,
    )


def simulate_topology_access(
    package: dict[str, Any],
    username: str,
    records: Iterable[dict[str, Any]],
    *,
    at: str,
) -> dict[str, Any]:
    """Simulate replicated IDs; UI visibility is intentionally not an input."""
    request_time = _parse_time(at)
    users = [_mapping(item) for item in _list(package.get("users"))]
    user = next((item for item in users if item.get("username") == username), None)
    all_records = [_mapping(item) for item in records]
    if request_time is None or not user or not _active_at(user, request_time):
        return {
            "username": username,
            "evaluated_at": at,
            "active": False,
            "replicated_node_ids": [],
            "replicated_record_ids": [],
        }
    types, nodes = _indexes(package)
    roles = {
        item.get("role"): item
        for item in (_mapping(raw) for raw in _list(_mapping(package.get("access_policy")).get("roles")))
        if isinstance(item.get("role"), str)
    }
    rule = roles.get(user.get("role"))
    if not rule:
        return {
            "username": username,
            "evaluated_at": at,
            "active": True,
            "role": user.get("role"),
            "replicated_node_ids": [],
            "replicated_record_ids": [],
        }
    candidates: set[str] = set()
    for assigned in _list(user.get("assigned_place_external_ids")):
        if assigned not in nodes or not _active_at(nodes[assigned], request_time):
            continue
        candidates.add(assigned)
        max_depth = rule.get("max_descendant_depth") if isinstance(rule.get("max_descendant_depth"), int) else None
        if rule.get("placement_scope") == "assigned-subtree":
            candidates.update(_descendants(package, assigned, request_time, max_depth))
        else:
            area = _responsible_area(package, assigned, request_time)
            if not area and types.get(str(nodes[assigned].get("contact_type")), {}).get("semantic") == "service-area":
                area = assigned
            if area:
                candidates.add(area)
                candidates.update(_descendants(package, area, request_time, max_depth))
        if rule.get("include_ancestors") is True:
            candidates.update(_ancestors(package, assigned, request_time))
    allowed_types = set(_list(rule.get("allowed_contact_types")))
    replicated_nodes = sorted(
        node_id
        for node_id in candidates
        if node_id in nodes and _active_at(nodes[node_id], request_time) and nodes[node_id].get("contact_type") in allowed_types
    )
    allowed_records = sorted(
        record.get("id")
        for record in all_records
        if isinstance(record.get("id"), str)
        and record.get("kind") in set(_list(rule.get("allowed_record_kinds")))
        and record.get("subject_external_id") in replicated_nodes
    )
    return {
        "username": username,
        "evaluated_at": at,
        "active": True,
        "role": user.get("role"),
        "replicated_node_ids": replicated_nodes,
        "replicated_record_ids": allowed_records,
    }


def resolve_topology_relation_for_user(
    package: dict[str, Any],
    username: str,
    request: dict[str, Any],
    records: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Apply role + placement + policy before resolving a subject relation."""
    request = _mapping(request)
    user = next((item for item in _list(package.get("users")) if _mapping(item).get("username") == username), None)
    if not user:
        return _resolution(package, request, "blocked", (), reason="Unknown user")
    roles = {
        _mapping(item).get("role"): _mapping(item)
        for item in _list(_mapping(package.get("access_policy")).get("roles"))
        if isinstance(_mapping(item).get("role"), str)
    }
    rule = roles.get(_mapping(user).get("role"))
    if not rule or request.get("relation") not in _list(rule.get("allowed_relations")):
        return _resolution(package, request, "blocked", (), reason="Role is not authorized to resolve this relation")
    simulation = simulate_topology_access(package, username, records, at=str(request.get("at", "")))
    if not simulation["active"]:
        return _resolution(package, request, "blocked", (), reason="User is inactive")
    subject = request.get("subject_external_id")
    if isinstance(subject, str):
        resolved_subject = _resolve_external_id(package, subject)
        if not resolved_subject or resolved_subject not in simulation["replicated_node_ids"]:
            return _resolution(package, request, "blocked", (), reason="Subject is outside the user replication scope")
    return resolve_topology_relation(package, request)


def assert_persona_isolation(simulation: dict[str, Any], forbidden_ids: Iterable[str]) -> None:
    replicated = set(_list(simulation.get("replicated_node_ids"))) | set(_list(simulation.get("replicated_record_ids")))
    leaked = sorted(set(forbidden_ids) & replicated)
    if leaked:
        raise OperationalValidationError(f"H-PERSONA prohibited data replicated: {', '.join(leaked)}")
