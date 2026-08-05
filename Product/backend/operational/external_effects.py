"""Prompt 10 planning contracts with no transport or callback ingress.

This module compiles reviewed external-effect requests into separately locked
planning artifacts.  It has deliberately no HTTP client, database, scheduler,
secret reader, provider adapter, webhook handler, template renderer, or
receipt normalizer.  Those deployment-owned concerns remain blocked until the
Prompt 10 runtime admission gates are met.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Iterable

from .contracts import OperationalValidationError


EFFECT_CHANNELS = {"sms", "whatsapp", "email", "push", "voice", "rapidpro-flow", "internal"}
EFFECT_URGENCIES = {"routine", "urgent", "emergency"}
EFFECT_RECIPIENT_RELATIONS = {
    "patient.primary-caregiver",
    "patient.assigned-chw",
    "patient.supervising-entity",
    "referral.eligible-facilities",
}
VALUE_TYPES = {"string", "integer", "number", "boolean", "date", "date-time", "code"}
SENSITIVITY_LEVELS = {"non-sensitive", "personal", "clinical"}
SENSITIVITY_RANK = {"non-sensitive": 0, "personal": 1, "clinical": 2}
FORBIDDEN_FIELD_TOKENS = {
    "address",
    "credential",
    "destination",
    "email",
    "endpoint",
    "password",
    "phone",
    "secret",
    "token",
    "url",
}
_EMAIL = re.compile(r"(?<![A-Z0-9._%+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![A-Z0-9._%+-])", re.IGNORECASE)
_PHONE = re.compile(r"\+?\d(?:[\d .()\-]{5,}\d)")
_PLACEHOLDER = re.compile(r"\{\{([A-Za-z][A-Za-z0-9_]*)\}\}")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OperationalValidationError(f"{label} must be an object")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise OperationalValidationError(f"{label} must be a list")
    return value


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OperationalValidationError(f"{label} must be a non-empty string")
    return value


def _parse_time(value: Any, label: str) -> datetime:
    text = _require_string(value, label)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise OperationalValidationError(f"{label} must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise OperationalValidationError(f"{label} must include a timezone offset")
    return parsed.astimezone(timezone.utc)


def _value_matches_type(value: Any, value_type: str) -> bool:
    """Keep template values typed before a future runtime can render them."""
    if value_type == "string":
        return isinstance(value, str)
    if value_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if value_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if value_type == "boolean":
        return isinstance(value, bool)
    if value_type == "date":
        return isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))
    if value_type == "date-time":
        try:
            _parse_time(value, "template variable")
        except OperationalValidationError:
            return False
        return True
    if value_type == "code":
        return isinstance(value, str) and bool(value.strip())
    return False


def _normalize_field_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _looks_like_raw_destination(value: str) -> bool:
    compact = value.strip()
    if _EMAIL.search(compact):
        return True
    # ISO dates contain many digits and hyphens but are not telephone numbers.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T[^\s]+)?", compact):
        return False
    without_dates = re.sub(r"\b\d{4}-\d{2}-\d{2}(?:T[^\s]+)?\b", "", compact)
    return any(len(re.sub(r"\D", "", match.group(0))) >= 7 for match in _PHONE.finditer(without_dates))


def _find_forbidden_values(value: Any, path: str = "") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            normalized = _normalize_field_name(str(key))
            if any(token in normalized for token in FORBIDDEN_FIELD_TOKENS):
                findings.append(child_path)
            findings.extend(_find_forbidden_values(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_forbidden_values(child, f"{path}[{index}]"))
    elif isinstance(value, str) and _looks_like_raw_destination(value):
        findings.append(path or "$")
    return findings


def assert_external_effect_requests_are_symbolic(requests: Iterable[Any]) -> None:
    """Reject contact/destination data before an operational package is persisted.

    The complete template, catalog, capability, and topology checks occur in
    :func:`build_external_effect_package`.  This earlier guard prevents an
    unsafe request from being recorded in ``operational_requirements.json``
    while the pipeline is gathering those separate reviewed inputs.
    """
    for raw_request in requests:
        request = _require_mapping(raw_request, "external effect request")
        forbidden = _find_forbidden_values(request)
        if forbidden:
            raise OperationalValidationError(
                "external effect request contains forbidden direct data: "
                + ", ".join(sorted(set(forbidden)))
            )


def _exact_reference(value: Any, label: str) -> tuple[str, str]:
    reference = _require_mapping(value, label)
    return (
        _require_string(reference.get("id"), f"{label}.id"),
        _require_string(reference.get("version"), f"{label}.version"),
    )


def _catalog_index(catalog: dict[str, Any], name: str) -> dict[tuple[str, str], dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_item in _require_list(catalog.get(name), f"external effect catalog.{name}"):
        item = _require_mapping(raw_item, f"external effect catalog.{name} entry")
        key = (
            _require_string(item.get("id"), f"external effect catalog.{name}.id"),
            _require_string(item.get("version"), f"external effect catalog.{name}.version"),
        )
        if key in index:
            raise OperationalValidationError(f"duplicate external effect catalog {name} entry: {key[0]}@{key[1]}")
        if item.get("status") != "active" or item.get("approved") is not True:
            raise OperationalValidationError(
                f"external effect catalog {name} entry must be active and approved: {key[0]}@{key[1]}"
            )
        index[key] = item
    return index


def _validate_template(template: dict[str, Any]) -> None:
    _require_string(template.get("purpose"), "template.purpose")
    channels = _require_list(template.get("channels"), "template.channels")
    if not channels or not set(channels).issubset(EFFECT_CHANNELS):
        raise OperationalValidationError("template.channels must contain supported effect channels")
    _require_string(template.get("approved_by"), "template.approved_by")
    _parse_time(template.get("approved_at"), "template.approved_at")
    variables: set[str] = set()
    for raw_variable in _require_list(template.get("variables"), "template.variables"):
        variable = _require_mapping(raw_variable, "template variable")
        name = _require_string(variable.get("name"), "template variable.name")
        if name in variables:
            raise OperationalValidationError(f"duplicate template variable: {name}")
        if variable.get("type") not in VALUE_TYPES:
            raise OperationalValidationError(f"template variable {name} has an unsupported type")
        if variable.get("sensitivity") not in SENSITIVITY_LEVELS:
            raise OperationalValidationError(f"template variable {name} has an unsupported sensitivity")
        if not isinstance(variable.get("required"), bool):
            raise OperationalValidationError(f"template variable {name} must declare required")
        variables.add(name)
    translations = _require_mapping(template.get("translations"), "template.translations")
    if not translations:
        raise OperationalValidationError("template.translations must not be empty")
    for locale, content in translations.items():
        _require_string(locale, "template locale")
        content = _require_string(content, f"template translation {locale}")
        if any(marker in content for marker in ("{%", "${", "{{{", "}}}")):
            raise OperationalValidationError("template translation contains an executable expression marker")
        placeholders = set(_PLACEHOLDER.findall(content))
        if placeholders - variables:
            raise OperationalValidationError("template translation uses an undeclared variable")
        remainder = _PLACEHOLDER.sub("", content)
        if "{{" in remainder or "}}" in remainder:
            raise OperationalValidationError("template translation has an invalid placeholder")


def _validate_policy(policy: dict[str, Any]) -> None:
    purposes = _require_list(policy.get("allowed_purposes"), "effect policy.allowed_purposes")
    if not purposes or any(not isinstance(item, str) or not item.strip() for item in purposes):
        raise OperationalValidationError("effect policy.allowed_purposes must contain non-empty strings")
    allowed_channels = _require_mapping(
        policy.get("allowed_channels_by_purpose"),
        "effect policy.allowed_channels_by_purpose",
    )
    for purpose in purposes:
        channels = _require_list(allowed_channels.get(purpose), f"effect policy.allowed_channels_by_purpose.{purpose}")
        if not channels or not set(channels).issubset(EFFECT_CHANNELS):
            raise OperationalValidationError(f"effect policy {purpose} has unsupported channels")
    consent_required = _require_list(policy.get("consent_required_purposes"), "effect policy.consent_required_purposes")
    if any(not isinstance(item, str) or not item.strip() for item in consent_required):
        raise OperationalValidationError("effect policy consent-required purposes must contain non-empty strings")
    if not set(consent_required).issubset(purposes):
        raise OperationalValidationError("effect policy consent-required purposes must be allowed purposes")
    emergency_overrides = _require_list(
        policy.get("emergency_consent_override_purposes"),
        "effect policy.emergency_consent_override_purposes",
    )
    if any(not isinstance(item, str) or not item.strip() for item in emergency_overrides):
        raise OperationalValidationError("effect policy emergency overrides must contain non-empty strings")
    if not set(emergency_overrides).issubset(set(consent_required)):
        raise OperationalValidationError("effect policy emergency overrides must be consent-required purposes")
    sensitivity_ceiling = _require_mapping(
        policy.get("channel_sensitivity_ceiling"),
        "effect policy.channel_sensitivity_ceiling",
    )
    allowed_channel_set = {
        channel
        for channels in allowed_channels.values()
        for channel in _require_list(channels, "effect policy.allowed_channels_by_purpose entry")
    }
    if set(sensitivity_ceiling) != allowed_channel_set:
        raise OperationalValidationError("effect policy must define one sensitivity ceiling for every allowed channel")
    if any(level not in SENSITIVITY_LEVELS for level in sensitivity_ceiling.values()):
        raise OperationalValidationError("effect policy channel sensitivity ceilings are unsupported")
    if policy.get("max_attempts") is not None:
        max_attempts = policy["max_attempts"]
        if not isinstance(max_attempts, int) or max_attempts < 1:
            raise OperationalValidationError("effect policy.max_attempts must be a positive integer")


def _validate_catalog(
    catalog: dict[str, Any],
) -> tuple[
    dict[tuple[str, str], dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
]:
    _require_string(catalog.get("id"), "external effect catalog.id")
    _require_string(catalog.get("version"), "external effect catalog.version")
    templates = _catalog_index(catalog, "templates")
    policies = _catalog_index(catalog, "policies")
    adapters = _catalog_index(catalog, "adapters")
    for template in templates.values():
        _validate_template(template)
    for policy in policies.values():
        _validate_policy(policy)
    for adapter in adapters.values():
        channels = _require_list(adapter.get("channels"), "adapter.channels")
        if not channels or not set(channels).issubset(EFFECT_CHANNELS):
            raise OperationalValidationError("adapter.channels must contain supported effect channels")
        for reference in _require_list(adapter.get("secret_references", []), "adapter.secret_references"):
            if not isinstance(reference, str) or not re.fullmatch(r"secret://[A-Za-z0-9._/-]+", reference):
                raise OperationalValidationError("adapter secret references must be opaque secret:// names")
    forbidden = _find_forbidden_values(catalog)
    # ``secret_references`` are the one allowed secret-shaped field and have
    # already been strictly checked above.
    forbidden = [path for path in forbidden if not path.endswith("secret_references")]
    if forbidden:
        raise OperationalValidationError(
            "external effect catalog contains forbidden direct data: "
            + ", ".join(sorted(set(forbidden)))
        )
    return templates, policies, adapters


def _validate_topology_lock(topology_lock: dict[str, Any]) -> dict[str, Any]:
    """Accept only the complete lock shape generated by the Prompt 9 layer."""
    if topology_lock.get("schema_version") != "1.0":
        raise OperationalValidationError("topology lock.schema_version must be 1.0")
    _require_string(topology_lock.get("resolver_version"), "topology lock.resolver_version")
    locked_topology = _require_mapping(topology_lock.get("topology_package"), "topology lock.topology_package")
    for field in ("id", "version", "snapshot_id"):
        _require_string(locked_topology.get(field), f"topology lock.topology_package.{field}")
    for field in (
        "content_digest",
        "schema_digest",
        "access_policy_digest",
        "capability_vocabulary_digest",
    ):
        digest = _require_string(locked_topology.get(field), f"topology lock.topology_package.{field}")
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
            raise OperationalValidationError(f"topology lock.topology_package.{field} must be a SHA-256 digest")
    return locked_topology


def _effect_identity_input(request: dict[str, Any]) -> dict[str, Any]:
    source = _require_mapping(request.get("source"), "external effect request.source")
    return {
        "schema_version": request.get("schema_version"),
        "source": {
            "package_id": source.get("package_id"),
            "package_version": source.get("package_version"),
            "trigger_id": source.get("trigger_id"),
            "trigger_event_id": source.get("trigger_event_id"),
            "episode_id": source.get("episode_id"),
        },
        "subject": request.get("subject"),
        "recipient_relation": request.get("recipient_relation"),
        "purpose": request.get("purpose"),
        "channel": request.get("channel"),
        "urgency": request.get("urgency"),
        "template": request.get("template"),
        "adapter": request.get("adapter"),
        "requested_at": request.get("requested_at"),
        "not_before": request.get("not_before"),
        "expires_at": request.get("expires_at"),
        "policy": request.get("policy"),
        "topology_snapshot_id": request.get("topology_snapshot_id"),
        "acknowledgment": request.get("acknowledgment"),
        "capability": request.get("capability"),
    }


def _effect_id(request: dict[str, Any]) -> str:
    return "effect-" + hashlib.sha256(_canonical_json(_effect_identity_input(request)).encode("utf-8")).hexdigest()[:32]


def _validate_request(
    request: dict[str, Any],
    *,
    resolved_capabilities: set[str],
    templates: dict[tuple[str, str], dict[str, Any]],
    policies: dict[tuple[str, str], dict[str, Any]],
    adapters: dict[tuple[str, str], dict[str, Any]],
    topology_lock: dict[str, Any],
) -> dict[str, Any]:
    if request.get("schema_version") != "1.0":
        raise OperationalValidationError("external effect request.schema_version must be 1.0")
    source = _require_mapping(request.get("source"), "external effect request.source")
    for field in ("package_id", "package_version", "trigger_id", "trigger_event_id"):
        _require_string(source.get(field), f"external effect request.source.{field}")
    provenance = _require_list(source.get("provenance"), "external effect request.source.provenance")
    if not provenance:
        raise OperationalValidationError("external effect request must retain source provenance")
    for raw_item in provenance:
        item = _require_mapping(raw_item, "external effect request provenance")
        _require_string(item.get("quotation"), "external effect request provenance.quotation")
        if not isinstance(item.get("page"), (int, str)):
            raise OperationalValidationError("external effect request provenance.page is required")

    _require_string(request.get("subject"), "external effect request.subject")
    relation = _require_string(request.get("recipient_relation"), "external effect request.recipient_relation")
    if relation not in EFFECT_RECIPIENT_RELATIONS:
        raise OperationalValidationError(f"unsupported external effect recipient relation: {relation}")
    capability = _require_string(request.get("capability"), "external effect request.capability")
    if capability not in resolved_capabilities:
        raise OperationalValidationError("external effect request must use an exact resolved capability")
    purpose = _require_string(request.get("purpose"), "external effect request.purpose")
    if request.get("channel") not in EFFECT_CHANNELS:
        raise OperationalValidationError("external effect request.channel is unsupported")
    if request.get("urgency") not in EFFECT_URGENCIES:
        raise OperationalValidationError("external effect request.urgency is unsupported")

    template_reference = _exact_reference(request.get("template"), "external effect request.template")
    template = templates.get(template_reference)
    if template is None:
        raise OperationalValidationError("external effect request pins an unknown approved template")
    locale = _require_string(request["template"].get("locale"), "external effect request.template.locale")
    if locale not in _require_mapping(template.get("translations"), "template.translations"):
        raise OperationalValidationError("external effect request template locale is not approved")
    variables = _require_mapping(request["template"].get("variables"), "external effect request.template.variables")
    declared = {item["name"]: item for item in _require_list(template.get("variables"), "template.variables")}
    if set(variables) - set(declared):
        raise OperationalValidationError("external effect request supplies undeclared template variables")
    missing_required = sorted(
        name for name, definition in declared.items() if definition.get("required") and name not in variables
    )
    if missing_required:
        raise OperationalValidationError(
            "external effect request omits required template variables: " + ", ".join(missing_required)
        )
    for name, value in variables.items():
        if not _value_matches_type(value, declared[name]["type"]):
            raise OperationalValidationError(
                f"external effect request variable {name} does not match its declared type"
            )

    policy_reference = _exact_reference(request.get("policy"), "external effect request.policy")
    policy = policies.get(policy_reference)
    if policy is None:
        raise OperationalValidationError("external effect request pins an unknown approved policy")
    if (
        purpose not in policy["allowed_purposes"]
        or request["channel"] not in policy["allowed_channels_by_purpose"][purpose]
    ):
        raise OperationalValidationError("external effect request purpose/channel is not permitted by policy")
    if purpose != template["purpose"] or request["channel"] not in template["channels"]:
        raise OperationalValidationError("external effect request does not match its approved template")
    adapter_reference = _exact_reference(request.get("adapter"), "external effect request.adapter")
    adapter = adapters.get(adapter_reference)
    if adapter is None:
        raise OperationalValidationError("external effect request pins an unknown approved adapter")
    if request["channel"] not in adapter["channels"]:
        raise OperationalValidationError("external effect request channel is not supported by its approved adapter")
    ceiling = policy["channel_sensitivity_ceiling"][request["channel"]]
    too_sensitive = sorted(
        name
        for name, definition in declared.items()
        if name in variables and SENSITIVITY_RANK[definition["sensitivity"]] > SENSITIVITY_RANK[ceiling]
    )
    if too_sensitive:
        raise OperationalValidationError(
            "external effect request has template variables above the channel sensitivity ceiling: "
            + ", ".join(too_sensitive)
        )

    requested_at = _parse_time(request.get("requested_at"), "external effect request.requested_at")
    not_before = (
        _parse_time(request["not_before"], "external effect request.not_before")
        if request.get("not_before")
        else None
    )
    expires_at = (
        _parse_time(request["expires_at"], "external effect request.expires_at")
        if request.get("expires_at")
        else None
    )
    if not_before and not_before < requested_at:
        raise OperationalValidationError("external effect request.not_before cannot precede requested_at")
    if expires_at and expires_at <= (not_before or requested_at):
        raise OperationalValidationError("external effect request.expires_at must follow its eligibility time")

    acknowledgment = request.get("acknowledgment", {"required": False})
    acknowledgment = _require_mapping(acknowledgment, "external effect request.acknowledgment")
    if not isinstance(acknowledgment.get("required"), bool):
        raise OperationalValidationError("external effect request acknowledgment.required must be Boolean")
    if acknowledgment["required"]:
        deadline = _parse_time(acknowledgment.get("deadline_at"), "external effect request acknowledgment.deadline_at")
        if deadline <= requested_at or (expires_at and deadline > expires_at):
            raise OperationalValidationError(
                "external effect request acknowledgment deadline is outside the request interval"
            )
        codes = _require_list(
            acknowledgment.get("accepted_codes"),
            "external effect request acknowledgment.accepted_codes",
        )
        if not codes or any(not isinstance(code, str) or not code.strip() for code in codes):
            raise OperationalValidationError("external effect request acknowledgment codes must be declared")

    locked_topology = _validate_topology_lock(topology_lock)
    if request.get("topology_snapshot_id") != locked_topology.get("snapshot_id"):
        raise OperationalValidationError("external effect request pins a different topology snapshot")
    assert_external_effect_requests_are_symbolic([request])

    compiled = json.loads(_canonical_json(request))
    identifier = _effect_id(compiled)
    if "id" in compiled and compiled["id"] != identifier:
        raise OperationalValidationError("external effect request ID does not match its deterministic content identity")
    compiled["id"] = identifier
    compiled["state"] = "requested"
    return compiled


def build_external_effect_package(
    requests: Iterable[dict[str, Any]],
    catalog: dict[str, Any],
    *,
    resolved_capabilities: Iterable[str],
    topology_lock: dict[str, Any],
    clinical_logic_content_sha256: str,
) -> dict[str, Any]:
    """Compile reviewed requests into a send-free Prompt 10 package."""
    if not re.fullmatch(r"[a-fA-F0-9]{64}", str(clinical_logic_content_sha256)):
        raise OperationalValidationError("clinical_logic_content_sha256 must be a SHA-256 hex digest")
    catalog = _require_mapping(catalog, "external effect catalog")
    topology_lock = _require_mapping(topology_lock, "topology lock")
    templates, policies, adapters = _validate_catalog(catalog)
    resolved = set(resolved_capabilities)
    compiled_requests = [
        _validate_request(
            _require_mapping(raw_request, "external effect request"),
            resolved_capabilities=resolved,
            templates=templates,
            policies=policies,
            adapters=adapters,
            topology_lock=topology_lock,
        )
        for raw_request in requests
    ]
    identifiers = [request["id"] for request in compiled_requests]
    if len(identifiers) != len(set(identifiers)):
        raise OperationalValidationError("external effect requests must have unique deterministic identities")
    lock = {
        "schema_version": "1.0",
        "clinical_logic_content_sha256": clinical_logic_content_sha256.lower(),
        "catalog": {
            "id": catalog["id"],
            "version": catalog["version"],
            "content_digest": _digest(catalog),
        },
        "topology_package": topology_lock["topology_package"],
        "resolved_capabilities": sorted(resolved),
        "requests_digest": _digest(compiled_requests),
        "runtime_status": "planning_only",
    }
    return {
        "schema_version": "1.0",
        "compile_status": "planned",
        "runtime_status": "planning_only",
        "external_effect_requests": compiled_requests,
        "version_lock": lock,
    }
