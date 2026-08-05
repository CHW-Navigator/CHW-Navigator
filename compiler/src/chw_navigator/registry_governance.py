from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .diagnostics import Diagnostic, DiagnosticCode
from .registry_set import CapabilityRegistry, Digest, TargetProfile, content_digest


DATA_DICTIONARY_SCHEMA_VERSION = "data-dictionary@1.0.0"
CAPABILITY_GOVERNANCE_SCHEMA_VERSION = "capability-governance@1.0.0"
REGISTRY_SET_V2_SCHEMA_VERSION = "registry-set@2.0.0"
APPROVAL_ATTESTATION_SCHEMA_VERSION = "approval-attestation@1.0.0"
REGISTRY_RELEASE_SCHEMA_VERSION = "registry-release@1.0.0"
REQUIRED_APPROVAL_ROLES = frozenset({"clinical", "data_governance", "technical"})

LifecycleState = Literal["candidate", "reviewed", "approved", "retired"]
ApprovalRole = Literal["clinical", "data_governance", "technical"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProvenanceRef(_StrictModel):
    source_id: str = Field(min_length=1)
    location: str = Field(min_length=1)


class ConceptIdentifier(_StrictModel):
    system: str = Field(min_length=1)
    code: str = Field(min_length=1)


class InteroperabilityMapping(_StrictModel):
    standard: str = Field(min_length=1)
    resource_type: str = Field(min_length=1)
    path: str = Field(min_length=1)
    code: str = Field(min_length=1)


class DataConcept(_StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    content_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    definition: str = Field(min_length=1)
    identifiers: tuple[ConceptIdentifier, ...] = Field(min_length=1)
    value_set: tuple[str, ...]
    type: Literal["boolean", "string", "integer", "decimal", "date", "datetime", "choice"]
    unit: str = Field(min_length=1)
    cardinality: Literal["required", "optional", "repeated"]
    requiredness: Literal["always", "conditional", "optional"]
    data_owner_role: str = Field(min_length=1)
    retention_policy_ref: str = Field(pattern=r"^[a-z][a-z0-9_.-]+@[0-9]+\.[0-9]+\.[0-9]+$")
    consent_policy_ref: str = Field(pattern=r"^[a-z][a-z0-9_.-]+@[0-9]+\.[0-9]+\.[0-9]+$")
    access_policy_ref: str = Field(pattern=r"^[a-z][a-z0-9_.-]+@[0-9]+\.[0-9]+\.[0-9]+$")
    interoperability_mappings: tuple[InteroperabilityMapping, ...]
    provenance: tuple[ProvenanceRef, ...] = Field(min_length=1)
    lifecycle_state: LifecycleState

    @model_validator(mode="after")
    def ordered_sets_are_unique(self) -> "DataConcept":
        identifiers = [(item.system, item.code) for item in self.identifiers]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("duplicate concept identifiers are forbidden")
        if len(self.value_set) != len(set(self.value_set)):
            raise ValueError("duplicate value-set entries are forbidden")
        if self.type == "choice" and not self.value_set:
            raise ValueError("choice concepts require a non-empty value_set")
        if self.type != "choice" and self.value_set:
            raise ValueError("only choice concepts may declare a value_set")
        return self


class DataDictionary(_StrictModel):
    schema_version: Literal[DATA_DICTIONARY_SCHEMA_VERSION]
    content_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    concepts: tuple[DataConcept, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def concept_identities_are_unique(self) -> "DataDictionary":
        identities = [(item.id, item.version) for item in self.concepts]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate concept id/version entries are forbidden")
        return self


class CapabilityGovernanceEntry(_StrictModel):
    capability_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    capability_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    capability_content_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    content_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_sources: tuple[ProvenanceRef, ...] = Field(min_length=1)
    owner_roles: tuple[str, ...] = Field(min_length=1)
    invocation_policy_ref: str = Field(pattern=r"^[a-z][a-z0-9_.-]+@[0-9]+\.[0-9]+\.[0-9]+$")
    review_requirements: tuple[ApprovalRole, ...] = Field(min_length=1)
    concept_bindings: tuple["CapabilityConceptBinding", ...]
    lifecycle_state: LifecycleState

    @model_validator(mode="after")
    def roles_are_unique(self) -> "CapabilityGovernanceEntry":
        if len(self.owner_roles) != len(set(self.owner_roles)):
            raise ValueError("duplicate capability owner roles are forbidden")
        if len(self.review_requirements) != len(set(self.review_requirements)):
            raise ValueError("duplicate review requirements are forbidden")
        identities = [(item.direction, item.parameter_name) for item in self.concept_bindings]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate capability concept bindings are forbidden")
        return self


class CapabilityConceptBinding(_StrictModel):
    direction: Literal["input", "output"]
    parameter_name: str = Field(min_length=1)
    concept_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    concept_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    concept_content_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")


CapabilityGovernanceEntry.model_rebuild()


class CapabilityGovernanceCatalogue(_StrictModel):
    schema_version: Literal[CAPABILITY_GOVERNANCE_SCHEMA_VERSION]
    content_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    entries: tuple[CapabilityGovernanceEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def capability_identities_are_unique(self) -> "CapabilityGovernanceCatalogue":
        identities = [(item.capability_id, item.capability_version) for item in self.entries]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate capability-governance entries are forbidden")
        return self


class RegistrySetV2(_StrictModel):
    schema_version: Literal[REGISTRY_SET_V2_SCHEMA_VERSION]
    content_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    data_dictionary: DataDictionary
    capability_registry: CapabilityRegistry
    capability_governance: CapabilityGovernanceCatalogue
    target_profile: TargetProfile


class ApprovalAttestation(_StrictModel):
    schema_version: Literal[APPROVAL_ATTESTATION_SCHEMA_VERSION]
    content_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    registry_set_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    role: ApprovalRole
    decision: Literal["approved", "rejected"]
    approver_id: str = Field(min_length=1)
    organization_id: str = Field(min_length=1)
    signed_at: datetime
    expires_at: datetime | None
    signing_key_id: str = Field(min_length=1)
    signature_algorithm: Literal["detached-external"]
    signature: str = Field(min_length=1)

    @field_validator("signed_at", "expires_at")
    @classmethod
    def timestamps_are_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("approval timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def expiry_follows_signature(self) -> "ApprovalAttestation":
        if self.expires_at is not None and self.expires_at <= self.signed_at:
            raise ValueError("approval expiry must be later than signed_at")
        return self


class RegistryRelease(_StrictModel):
    schema_version: Literal[REGISTRY_RELEASE_SCHEMA_VERSION]
    content_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    release_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    registry_set_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    attestation_digests: tuple[Digest, ...] = Field(min_length=3)
    effective_from: datetime
    expires_at: datetime | None
    supersedes_release_digest: Digest | None

    @field_validator("effective_from", "expires_at")
    @classmethod
    def timestamps_are_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("release timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def attestation_digests_are_unique(self) -> "RegistryRelease":
        if len(self.attestation_digests) != len(set(self.attestation_digests)):
            raise ValueError("duplicate attestation digests are forbidden")
        if self.expires_at is not None and self.expires_at <= self.effective_from:
            raise ValueError("release expiry must be later than effective_from")
        return self


class ActivatedRegistryRelease(_StrictModel):
    release_digest: Digest
    registry_set_digest: Digest
    attestation_digests: tuple[Digest, ...]
    activated_at: datetime


class RegistryGovernanceError(ValueError):
    def __init__(self, diagnostics: list[Diagnostic] | tuple[Diagnostic, ...]):
        self.diagnostics = tuple(diagnostics)
        super().__init__(
            "Registry governance failed closed:\n"
            + "\n".join(f"{item.code}: {item.message}" for item in self.diagnostics)
        )


SignatureVerifier = Callable[[ApprovalAttestation], bool]


def _diagnostic(code: DiagnosticCode, message: str, path: str | None = None) -> Diagnostic:
    return Diagnostic(code=code, severity="error", message=message, path=path)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _set_digest(member_digests: dict[str, str]) -> str:
    return f"sha256:{hashlib.sha256(_canonical_json(member_digests)).hexdigest()}"


def seal_registry_set_v2(payload: dict[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(payload)
    dictionary = sealed["data_dictionary"]
    for concept in dictionary["concepts"]:
        concept["content_digest"] = content_digest(concept)
    dictionary["content_digest"] = content_digest(dictionary)

    registry = sealed["capability_registry"]
    for capability in registry["capabilities"]:
        capability["content_digest"] = content_digest(capability)
    registry["content_digest"] = content_digest(registry)

    governance = sealed["capability_governance"]
    for entry in governance["entries"]:
        entry["content_digest"] = content_digest(entry)
    governance["content_digest"] = content_digest(governance)

    target = sealed["target_profile"]
    target["content_digest"] = content_digest(target)
    sealed["content_digest"] = _set_digest(
        {
            "capability_governance": governance["content_digest"],
            "capability_registry": registry["content_digest"],
            "data_dictionary": dictionary["content_digest"],
            "target_profile": target["content_digest"],
        }
    )
    return sealed


def seal_attestation(payload: dict[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(payload)
    sealed["content_digest"] = content_digest(sealed)
    return sealed


def seal_registry_release(payload: dict[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(payload)
    sealed["content_digest"] = content_digest(sealed)
    return sealed


def _parse(model: type[BaseModel], payload: Any) -> BaseModel:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        diagnostics = [
            _diagnostic(
                DiagnosticCode.REGISTRY_SCHEMA_INVALID,
                str(item["msg"]),
                "$" + "".join(
                    f"[{part}]" if isinstance(part, int) else f".{part}" for part in item["loc"]
                ),
            )
            for item in exc.errors(include_url=False)
        ]
        raise RegistryGovernanceError(diagnostics) from exc


def parse_registry_set_v2(payload: Any) -> RegistrySetV2:
    document = _parse(RegistrySetV2, payload)
    assert isinstance(document, RegistrySetV2)
    expected = seal_registry_set_v2(document.model_dump(mode="json"))
    diagnostics: list[Diagnostic] = []
    _collect_digest_mismatches(document.model_dump(mode="json"), expected, "$", diagnostics)
    if diagnostics:
        raise RegistryGovernanceError(diagnostics)
    _validate_governance_bindings(document)
    return document


def load_registry_set_v2(path: str | Path) -> RegistrySetV2:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryGovernanceError(
            [_diagnostic(DiagnosticCode.REGISTRY_SCHEMA_INVALID, f"Could not load governed registry set: {exc}", str(source))]
        ) from exc
    return parse_registry_set_v2(payload)


def parse_attestation(payload: Any) -> ApprovalAttestation:
    document = _parse(ApprovalAttestation, payload)
    assert isinstance(document, ApprovalAttestation)
    if document.content_digest != content_digest(document):
        raise RegistryGovernanceError(
            [_diagnostic(DiagnosticCode.REGISTRY_DIGEST_MISMATCH, "Approval attestation content digest does not match.", "$.content_digest")]
        )
    return document


def parse_registry_release(payload: Any) -> RegistryRelease:
    document = _parse(RegistryRelease, payload)
    assert isinstance(document, RegistryRelease)
    if document.content_digest != content_digest(document):
        raise RegistryGovernanceError(
            [_diagnostic(DiagnosticCode.REGISTRY_DIGEST_MISMATCH, "Registry release content digest does not match.", "$.content_digest")]
        )
    return document


def _collect_digest_mismatches(actual: Any, expected: Any, path: str, diagnostics: list[Diagnostic]) -> None:
    if isinstance(actual, dict) and isinstance(expected, dict):
        for key in actual:
            child = f"{path}.{key}"
            if key == "content_digest" and actual[key] != expected[key]:
                diagnostics.append(
                    _diagnostic(
                        DiagnosticCode.REGISTRY_DIGEST_MISMATCH,
                        f"Locked content digest does not match canonical content; expected {expected[key]}.",
                        child,
                    )
                )
            else:
                _collect_digest_mismatches(actual[key], expected.get(key), child, diagnostics)
    elif isinstance(actual, list) and isinstance(expected, list):
        for index, value in enumerate(actual):
            _collect_digest_mismatches(value, expected[index], f"{path}[{index}]", diagnostics)


def _validate_governance_bindings(document: RegistrySetV2) -> None:
    capabilities = {(item.id, item.version): item for item in document.capability_registry.capabilities}
    concepts = {(item.id, item.version): item for item in document.data_dictionary.concepts}
    diagnostics: list[Diagnostic] = []
    for index, entry in enumerate(document.capability_governance.entries):
        capability = capabilities.get((entry.capability_id, entry.capability_version))
        if capability is None or capability.content_digest != entry.capability_content_digest:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.REGISTRY_APPROVAL_DIGEST_MISMATCH,
                    "Capability-governance entry does not bind the exact executable capability digest.",
                    f"$.capability_governance.entries[{index}].capability_content_digest",
                )
            )
            continue
        parameters = {
            "input": {item.name: item for item in capability.inputs},
            "output": {item.name: item for item in capability.outputs},
        }
        for binding_index, binding in enumerate(entry.concept_bindings):
            concept = concepts.get((binding.concept_id, binding.concept_version))
            parameter = parameters[binding.direction].get(binding.parameter_name)
            if (
                concept is None
                or concept.content_digest != binding.concept_content_digest
                or parameter is None
                or concept.type != parameter.type
                or concept.unit != parameter.unit
            ):
                diagnostics.append(
                    _diagnostic(
                        DiagnosticCode.REGISTRY_CONCEPT_BINDING_INVALID,
                        "Capability concept binding must match exact concept and parameter digests, types, and units.",
                        f"$.capability_governance.entries[{index}].concept_bindings[{binding_index}]",
                    )
                )
    governed = {(item.capability_id, item.capability_version) for item in document.capability_governance.entries}
    missing = sorted(set(capabilities) - governed)
    if missing:
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.REGISTRY_INPUT_INACTIVE,
                "Executable capabilities lack governance entries: "
                + ", ".join(f"{identifier}@{version}" for identifier, version in missing)
                + ".",
                "$.capability_governance.entries",
            )
        )
    if diagnostics:
        raise RegistryGovernanceError(diagnostics)


def activate_registry_release(
    registry_set: Any,
    release: RegistryRelease,
    attestations: tuple[ApprovalAttestation, ...] | list[ApprovalAttestation],
    *,
    verifier: SignatureVerifier,
    at: datetime | None = None,
    superseded_release_digests: frozenset[str] = frozenset(),
) -> ActivatedRegistryRelease:
    now = at or datetime.now(timezone.utc)
    diagnostics: list[Diagnostic] = []
    if not isinstance(registry_set, RegistrySetV2):
        raise RegistryGovernanceError(
            [_diagnostic(DiagnosticCode.REGISTRY_RELEASE_REQUIRES_V2, "Governed activation requires registry-set@2.0.0.", "$.registry_set")]
        )
    registry_set = parse_registry_set_v2(registry_set.model_dump(mode="json"))
    release = parse_registry_release(release.model_dump(mode="json"))
    attestations = [parse_attestation(item.model_dump(mode="json")) for item in attestations]
    if release.content_digest in superseded_release_digests:
        diagnostics.append(
            _diagnostic(DiagnosticCode.REGISTRY_INPUT_INACTIVE, "Registry release has been superseded.", "$.release.content_digest")
        )
    if release.registry_set_digest != registry_set.content_digest:
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.REGISTRY_APPROVAL_DIGEST_MISMATCH,
                "Registry release does not bind the supplied registry-set digest.",
                "$.release.registry_set_digest",
            )
        )
    if release.effective_from > now or (release.expires_at is not None and release.expires_at <= now):
        diagnostics.append(
            _diagnostic(DiagnosticCode.REGISTRY_INPUT_INACTIVE, "Registry release is not active at the evaluation time.", "$.release")
        )

    roles: dict[str, int] = {}
    approver_ids: list[str] = []
    actual_attestation_digests = {item.content_digest for item in attestations}
    if set(release.attestation_digests) != actual_attestation_digests:
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.REGISTRY_APPROVAL_DIGEST_MISMATCH,
                "Registry release attestation digests do not exactly match the supplied attestations.",
                "$.release.attestation_digests",
            )
        )
    for index, attestation in enumerate(attestations):
        roles[attestation.role] = roles.get(attestation.role, 0) + 1
        approver_ids.append(attestation.approver_id)
        if attestation.registry_set_digest != registry_set.content_digest:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.REGISTRY_APPROVAL_DIGEST_MISMATCH,
                    "Approval attestation does not bind the supplied registry-set digest.",
                    f"$.attestations[{index}].registry_set_digest",
                )
            )
        if attestation.decision != "approved":
            diagnostics.append(
                _diagnostic(DiagnosticCode.REGISTRY_APPROVAL_REJECTED, "A required approval decision is not approved.", f"$.attestations[{index}].decision")
            )
        if attestation.expires_at is not None and attestation.expires_at <= now:
            diagnostics.append(
                _diagnostic(DiagnosticCode.REGISTRY_APPROVAL_EXPIRED, "Approval attestation is expired.", f"$.attestations[{index}].expires_at")
            )
        if attestation.signed_at > now:
            diagnostics.append(
                _diagnostic(DiagnosticCode.REGISTRY_INPUT_INACTIVE, "Approval attestation is future-dated.", f"$.attestations[{index}].signed_at")
            )
        verified = False
        try:
            verified = verifier(attestation)
        except Exception:
            verified = False
        if not verified:
            diagnostics.append(
                _diagnostic(DiagnosticCode.REGISTRY_APPROVAL_UNVERIFIED, "Detached approval signature was not verified.", f"$.attestations[{index}].signature")
            )

    missing = sorted(REQUIRED_APPROVAL_ROLES - set(roles))
    if missing:
        diagnostics.append(
            _diagnostic(DiagnosticCode.REGISTRY_APPROVAL_ROLE_MISSING, f"Missing required approval roles: {', '.join(missing)}.", "$.attestations")
        )
    duplicate = sorted(role for role, count in roles.items() if count > 1)
    duplicate_approvers = sorted({item for item in approver_ids if approver_ids.count(item) > 1})
    if duplicate or duplicate_approvers:
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.REGISTRY_APPROVAL_ROLE_DUPLICATE,
                "Required approval roles and approver identities must be distinct; duplicates: "
                + ", ".join(duplicate + duplicate_approvers)
                + ".",
                "$.attestations",
            )
        )

    inactive_members = [
        f"concept:{item.id}@{item.version}"
        for item in registry_set.data_dictionary.concepts
        if item.lifecycle_state != "approved"
    ]
    inactive_members.extend(
        f"capability:{item.id}@{item.version}"
        for item in registry_set.capability_registry.capabilities
        if item.evidence_status == "candidate"
    )
    inactive_members.extend(
        f"governance:{item.capability_id}@{item.capability_version}"
        for item in registry_set.capability_governance.entries
        if item.lifecycle_state != "approved"
    )
    if inactive_members:
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.REGISTRY_INPUT_INACTIVE,
                f"Registry release contains inactive inputs: {', '.join(inactive_members)}.",
                "$.registry_set",
            )
        )

    if diagnostics:
        raise RegistryGovernanceError(diagnostics)
    return ActivatedRegistryRelease(
        release_digest=release.content_digest,
        registry_set_digest=registry_set.content_digest,
        attestation_digests=release.attestation_digests,
        activated_at=now,
    )
