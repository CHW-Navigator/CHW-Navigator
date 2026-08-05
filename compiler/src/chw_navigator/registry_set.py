from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .diagnostics import Diagnostic, DiagnosticCode


REGISTRY_SET_SCHEMA_VERSION = "registry-set@1.0.0"
CAPABILITY_REGISTRY_SCHEMA_VERSION = "capability-registry@1.0.0"
TARGET_PROFILE_SCHEMA_VERSION = "target-profile@1.0.0"
RELEASE_1_SUBJECT_SCOPE = "current_contact"
GROUP_SUBJECT_SCOPES = frozenset({"household", "service_area", "cohort"})

Digest = str
ValueType = Literal["boolean", "string", "integer", "decimal", "date", "datetime", "choice"]
SubjectScope = Literal["current_contact", "household", "service_area", "cohort"]
CapabilityStatus = Literal[
    "ok",
    "input_missing",
    "input_invalid",
    "outside_supported_domain",
    "reference_data_unavailable",
    "numeric_failure",
    "version_mismatch",
    "execution_failure",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CapabilityInput(_StrictModel):
    name: str = Field(min_length=1)
    type: ValueType
    unit: str = Field(min_length=1)
    cardinality: Literal["required", "optional", "repeated"]


class CapabilityOutput(_StrictModel):
    name: str = Field(min_length=1)
    type: ValueType
    unit: str = Field(min_length=1)
    binding_path: str = Field(pattern=r"^technical\.[a-z0-9_.-]+$")


class SupportedDomain(_StrictModel):
    basis: str = Field(min_length=1)
    minimum: int | float
    maximum: int | float
    unit: str = Field(min_length=1)

    @model_validator(mode="after")
    def bounds_are_ordered(self) -> "SupportedDomain":
        if self.minimum > self.maximum:
            raise ValueError("supported-domain minimum cannot exceed maximum")
        return self


class ImplementationBinding(_StrictModel):
    kind: Literal["python_cht_extension"]
    python_module: str = Field(min_length=1)
    python_symbol: str = Field(min_length=1)
    cht_extension_module: str = Field(pattern=r"^[a-z0-9_.-]+\.js$")


class Capability(_StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    content_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    family: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    inputs: tuple[CapabilityInput, ...] = Field(min_length=1)
    outputs: tuple[CapabilityOutput, ...] = Field(min_length=1)
    status_set: tuple[CapabilityStatus, ...] = Field(min_length=1)
    supported_domain: SupportedDomain
    rounding: Literal["none", "half_even"]
    determinism: Literal["deterministic", "nondeterministic"]
    side_effects: tuple[str, ...]
    implementation_binding: ImplementationBinding
    evidence_status: Literal["candidate", "tracer_enabled"]
    supported_target_profiles: tuple[str, ...] = Field(min_length=1)
    subject_scope: SubjectScope

    @model_validator(mode="after")
    def ordered_names_and_sets_are_unique(self) -> "Capability":
        for label, values in (
            ("input", [item.name for item in self.inputs]),
            ("output", [item.name for item in self.outputs]),
            ("status", list(self.status_set)),
            ("target profile", list(self.supported_target_profiles)),
            ("side effect", list(self.side_effects)),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {label} entries are forbidden")
        return self


class CapabilityRegistry(_StrictModel):
    schema_version: Literal[CAPABILITY_REGISTRY_SCHEMA_VERSION]
    content_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    capabilities: tuple[Capability, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def capability_ids_are_unique(self) -> "CapabilityRegistry":
        identities = [(item.id, item.version) for item in self.capabilities]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate capability id/version entries are forbidden")
        return self


class FormEngine(_StrictModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)


class ExtensionSupport(_StrictModel):
    extension_lib_xpath: bool
    extension_lib_expression: bool


LocalDataFeature = Literal[
    "contact_summary",
    "registered_local_read",
    "latest_value_ordering",
    "recorded_at_freshness",
]


class TargetProfile(_StrictModel):
    schema_version: Literal[TARGET_PROFILE_SCHEMA_VERSION]
    id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    content_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    cht_core_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    cht_conf_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    form_engine: FormEngine
    extension_support: ExtensionSupport
    required_local_data_features: tuple[LocalDataFeature, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def features_are_unique(self) -> "TargetProfile":
        if len(self.required_local_data_features) != len(set(self.required_local_data_features)):
            raise ValueError("duplicate local-data features are forbidden")
        return self

    @property
    def reference(self) -> str:
        return f"{self.id}@{self.version}"


class RegistrySet(_StrictModel):
    schema_version: Literal[REGISTRY_SET_SCHEMA_VERSION]
    content_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    capability_registry: CapabilityRegistry
    target_profile: TargetProfile


class RegistrySetError(ValueError):
    def __init__(self, diagnostics: list[Diagnostic] | tuple[Diagnostic, ...]):
        self.diagnostics = tuple(diagnostics)
        super().__init__(
            "Registry-set validation failed closed:\n"
            + "\n".join(f"{item.code}: {item.message}" for item in self.diagnostics)
        )


def _diagnostic(code: DiagnosticCode, message: str, path: str | None = None) -> Diagnostic:
    return Diagnostic(code=code, severity="error", message=message, path=path)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_digest(value: BaseModel | dict[str, Any]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else copy.deepcopy(value)
    payload.pop("content_digest", None)
    return f"sha256:{hashlib.sha256(_canonical_json(payload)).hexdigest()}"


def seal_registry_set(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with all member and set digests recomputed from content."""
    sealed = copy.deepcopy(payload)
    registry = sealed["capability_registry"]
    for capability in registry["capabilities"]:
        capability["content_digest"] = content_digest(capability)
    registry["content_digest"] = content_digest(registry)
    target = sealed["target_profile"]
    target["content_digest"] = content_digest(target)
    sealed["content_digest"] = _registry_set_digest_from_members(
        registry["content_digest"], target["content_digest"]
    )
    return sealed


def compute_registry_set_digest(payload: RegistrySet | dict[str, Any]) -> str:
    raw = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else copy.deepcopy(payload)
    return seal_registry_set(raw)["content_digest"]


def _registry_set_digest_from_members(capability_registry_digest: str, target_profile_digest: str) -> str:
    members = {
        "capability_registry": capability_registry_digest,
        "target_profile": target_profile_digest,
    }
    return f"sha256:{hashlib.sha256(_canonical_json(members)).hexdigest()}"


def load_registry_set(path: str | Path) -> RegistrySet:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistrySetError(
            [_diagnostic(DiagnosticCode.REGISTRY_SCHEMA_INVALID, f"Could not load registry set: {exc}", str(source))]
        ) from exc
    return parse_registry_set(payload)


def parse_registry_set(payload: Any) -> RegistrySet:
    try:
        document = RegistrySet.model_validate(payload)
    except ValidationError as exc:
        raise RegistrySetError(_validation_diagnostics(exc)) from exc

    diagnostics: list[Diagnostic] = []
    for index, capability in enumerate(document.capability_registry.capabilities):
        _check_digest(
            capability.content_digest,
            content_digest(capability),
            f"$.capability_registry.capabilities[{index}].content_digest",
            diagnostics,
        )
    _check_digest(
        document.capability_registry.content_digest,
        content_digest(document.capability_registry),
        "$.capability_registry.content_digest",
        diagnostics,
    )
    _check_digest(
        document.target_profile.content_digest,
        content_digest(document.target_profile),
        "$.target_profile.content_digest",
        diagnostics,
    )
    expected_set_digest = _registry_set_digest_from_members(
        content_digest(document.capability_registry),
        content_digest(document.target_profile),
    )
    _check_digest(document.content_digest, expected_set_digest, "$.content_digest", diagnostics)
    if diagnostics:
        raise RegistrySetError(diagnostics)
    return document


def _check_digest(actual: str, expected: str, path: str, diagnostics: list[Diagnostic]) -> None:
    if actual != expected:
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.REGISTRY_DIGEST_MISMATCH,
                f"Locked content digest does not match canonical content; expected {expected}.",
                path,
            )
        )


def _validation_diagnostics(exc: ValidationError) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    seen: set[tuple[DiagnosticCode, str]] = set()
    for error in exc.errors(include_url=False):
        loc = tuple(error["loc"])
        path = "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in loc)
        field = str(loc[-1]) if loc else ""
        kind = error["type"]
        if kind == "missing" and field == "unit":
            code = DiagnosticCode.REGISTRY_UNIT_MISSING
            message = "Every capability input and output must declare a unit."
        elif kind == "missing" and field == "version":
            code = DiagnosticCode.REGISTRY_VERSION_MISSING
            message = "Every versioned registry member must declare a version."
        elif kind == "missing" and field == "content_digest":
            code = DiagnosticCode.REGISTRY_DIGEST_MISSING
            message = "Every locked registry member and registry set must declare a content digest."
        elif kind == "missing" and field == "subject_scope":
            code = DiagnosticCode.SUBJECT_SCOPE_MISSING
            message = "Every capability must declare its subject scope."
        elif kind == "missing" and field == "required_local_data_features":
            code = DiagnosticCode.TARGET_FEATURE_MISSING
            message = "A target profile must declare the local-data features required by the build."
        elif kind == "extra_forbidden":
            code = DiagnosticCode.REGISTRY_UNKNOWN_FIELD
            message = "Unknown registry fields are rejected; they are never silently dropped."
        else:
            code = DiagnosticCode.REGISTRY_SCHEMA_INVALID
            message = str(error["msg"])
        identity = (code, path)
        if identity not in seen:
            diagnostics.append(_diagnostic(code, message, path))
            seen.add(identity)
    return diagnostics or [
        _diagnostic(DiagnosticCode.REGISTRY_SCHEMA_INVALID, "Registry set did not satisfy its contract.", "$")
    ]


def validate_release1_subject_scope(scope: str) -> tuple[Diagnostic, ...]:
    if scope == RELEASE_1_SUBJECT_SCOPE:
        return ()
    if scope in GROUP_SUBJECT_SCOPES:
        return (
            _diagnostic(
                DiagnosticCode.SUBJECT_SCOPE_GROUP_UNSUPPORTED,
                f"Subject scope '{scope}' requires a separate group-obligation model; Release 1 supports current_contact only.",
                "$.subject_scope",
            ),
        )
    return (
        _diagnostic(
            DiagnosticCode.REGISTRY_SCHEMA_INVALID,
            f"Unknown subject scope '{scope}'.",
            "$.subject_scope",
        ),
    )


def resolve_capability(
    registry_set: RegistrySet,
    capability_id: str,
    *,
    required_target_features: tuple[str, ...] = (),
) -> Capability:
    capability = next(
        (item for item in registry_set.capability_registry.capabilities if item.id == capability_id),
        None,
    )
    if capability is None:
        raise RegistrySetError(
            [_diagnostic(DiagnosticCode.REGISTRY_SCHEMA_INVALID, f"Capability '{capability_id}' is not registered.")]
        )
    diagnostics: list[Diagnostic] = []
    if capability.evidence_status == "candidate":
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.REGISTRY_CANDIDATE_UNRESOLVED,
                f"Candidate capability '{capability.id}' is schema-valid but cannot resolve.",
                "$.capability_registry.capabilities",
            )
        )
    profile = registry_set.target_profile
    if profile.reference not in capability.supported_target_profiles:
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.TARGET_PROFILE_UNSUPPORTED,
                f"Capability '{capability.id}' does not support target profile '{profile.reference}'.",
                "$.target_profile",
            )
        )
    available_features = set(profile.required_local_data_features)
    available_features.update(
        name
        for name, supported in profile.extension_support.model_dump().items()
        if supported
    )
    missing_features = sorted(set(required_target_features) - available_features)
    if missing_features:
        diagnostics.append(
            _diagnostic(
                DiagnosticCode.TARGET_FEATURE_MISSING,
                f"Target profile '{profile.reference}' lacks required features: {', '.join(missing_features)}.",
                "$.target_profile.required_local_data_features",
            )
        )
    diagnostics.extend(validate_release1_subject_scope(capability.subject_scope))
    if diagnostics:
        raise RegistrySetError(diagnostics)
    return capability
