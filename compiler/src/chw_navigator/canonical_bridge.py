from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cht_local_data import CHTLocalDataRegistry, load_cht_local_data_registry
from .clinical_ir import ClinicalIRDocument
from .diagnostics import Diagnostic, DiagnosticCode
from .registry_governance import (
    ActivatedRegistryRelease,
    RegistrySetV2,
    load_registry_set_v2,
    parse_registry_set_v2,
)
from .registry_set import Capability, TargetProfile, content_digest
from .validator import validate_document


ADAPTER_SCHEMA_VERSION = "product-canonical-adapter@1.0.0"
REVIEWED_NEEDS_SCHEMA_VERSION = "reviewed-capability-needs@1.0.0"
LOSS_REPORT_SCHEMA_VERSION = "product-canonical-loss-report@1.0.0"
RESOLUTION_LOCK_SCHEMA_VERSION = "capability-resolution-lock@1.0.0"
RESOLUTION_RULE_VERSION = "exact-semantic-resolution@1.0.0"
RESOLUTION_MATCHED_FIELDS = (
    "family", "operation", "ordered_inputs", "ordered_outputs", "status_set",
    "target_profile", "subject_scope", "approved_governance",
)
RESOLUTION_FORBIDDEN_SELECTORS = (
    "string_similarity", "registry_order", "implementation_name",
    "model_preference", "closest_match",
)
PRODUCT_SECTIONS = (
    "supply_list",
    "variables",
    "predicates",
    "modules",
    "router",
    "integrative",
    "phrase_bank",
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


ValueType = Literal["boolean", "string", "integer", "decimal", "date", "datetime", "choice"]


class ReviewedParameterBinding(_StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    type: ValueType
    unit: str = Field(min_length=1)
    variable_id: str = Field(pattern=r"^(v_|h_|st_)[a-z0-9_]+$")


class ReviewedCapabilityNeed(_StrictModel):
    need_id: str = Field(pattern=r"^need_[a-z0-9_]+$")
    family: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    operation: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    inputs: tuple[ReviewedParameterBinding, ...] = Field(min_length=1)
    outputs: tuple[ReviewedParameterBinding, ...] = Field(min_length=1)
    required_statuses: tuple[str, ...] = Field(min_length=1)
    status_target_var: str = Field(pattern=r"^st_[a-z0-9_]+$")
    target_profile: str = Field(pattern=r"^[a-z][a-z0-9_.-]+@[0-9]+\.[0-9]+\.[0-9]+$")
    subject_scope: Literal["current_contact", "household", "service_area", "cohort"]
    source: dict[str, str]

    @model_validator(mode="after")
    def ordered_fields_are_unique(self) -> "ReviewedCapabilityNeed":
        for label, values in (("input", self.inputs), ("output", self.outputs)):
            names = [item.name for item in values]
            variables = [item.variable_id for item in values]
            if len(names) != len(set(names)):
                raise ValueError(f"duplicate {label} parameter names are forbidden")
            if len(variables) != len(set(variables)):
                raise ValueError(f"duplicate {label} variable bindings are forbidden")
        if len(self.required_statuses) != len(set(self.required_statuses)):
            raise ValueError("duplicate required statuses are forbidden")
        if set(self.source) != {"document_id", "page", "section", "quote"}:
            raise ValueError("source must contain exactly document_id, page, section, and quote")
        if not all(isinstance(value, str) and value for value in self.source.values()):
            raise ValueError("source values must be non-empty strings")
        return self


class ReviewedCapabilityNeeds(_StrictModel):
    schema_version: Literal[REVIEWED_NEEDS_SCHEMA_VERSION]
    content_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    authoring_origin: Literal["prompt_b", "human"]
    source_candidate_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    needs: tuple[ReviewedCapabilityNeed, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def need_ids_are_unique(self) -> "ReviewedCapabilityNeeds":
        identities = [item.need_id for item in self.needs]
        if len(identities) != len(set(identities)):
            raise ValueError("reviewed need IDs must be unique")
        return self


class LocalDataReadBinding(_StrictModel):
    action_id: str = Field(pattern=r"^a_[a-z0-9_]+$")
    binding_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+@[0-9]+\.[0-9]+\.[0-9]+$")
    target_var: str = Field(pattern=r"^(h_|st_)[a-z0-9_]+(?:_h)?$")
    recorded_at_target_var: str | None = Field(default=None, pattern=r"^(h_|st_)[a-z0-9_]+(?:_h)?$")
    fail_mode: Literal["soft_missing", "ask_if_missing", "hard_error"]


class TaskIntentBinding(_StrictModel):
    action_id: str = Field(pattern=r"^a_[a-z0-9_]+$")
    task_type: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    when_output: str = Field(pattern=r"^o_[a-z0-9_]+$")
    due_in_days: int = Field(ge=0)
    priority: str = Field(min_length=1)
    assignee_role: str = Field(min_length=1)
    message_key: str = Field(pattern=r"^m_[a-z0-9_]+$")
    message_text: str = Field(min_length=1)


class ProductCanonicalAdapter(_StrictModel):
    schema_version: Literal[ADAPTER_SCHEMA_VERSION]
    content_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    guideline_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    source_id: str = Field(min_length=1)
    product_schema_version: Literal["clinical-logic@gen8-v1"]
    local_data_reads: tuple[LocalDataReadBinding, ...]
    task_intents: tuple[TaskIntentBinding, ...]

    @model_validator(mode="after")
    def local_read_ids_are_unique(self) -> "ProductCanonicalAdapter":
        actions = [item.action_id for item in self.local_data_reads] + [
            item.action_id for item in self.task_intents
        ]
        targets = [item.target_var for item in self.local_data_reads]
        if len(actions) != len(set(actions)) or len(targets) != len(set(targets)):
            raise ValueError("adapter action IDs and local-data target variables must be unique")
        message_keys = [item.message_key for item in self.task_intents]
        if len(message_keys) != len(set(message_keys)):
            raise ValueError("task message keys must be unique")
        return self


@dataclass(frozen=True, slots=True)
class BridgeResult:
    canonical_ir: dict[str, Any] | None
    loss_report: dict[str, Any]


@dataclass(frozen=True, slots=True)
class WS5Package:
    canonical_ir: dict[str, Any]
    loss_report: dict[str, Any]
    resolution_lock: dict[str, Any]


class CanonicalBridgeError(ValueError):
    def __init__(self, diagnostics: list[Diagnostic] | tuple[Diagnostic, ...]):
        self.diagnostics = tuple(diagnostics)
        super().__init__(
            "Canonical bridge failed closed:\n"
            + "\n".join(f"{item.code}: {item.message}" for item in self.diagnostics)
        )


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _seal(payload: dict[str, Any]) -> dict[str, Any]:
    sealed = deepcopy(payload)
    sealed["content_digest"] = "sha256:" + "0" * 64
    sealed["content_digest"] = content_digest(sealed)
    return sealed


def seal_product_adapter(payload: dict[str, Any]) -> dict[str, Any]:
    return _seal(payload)


def seal_reviewed_needs(payload: dict[str, Any]) -> dict[str, Any]:
    return _seal(payload)


def _diagnostic(code: DiagnosticCode, message: str, path: str | None = None) -> Diagnostic:
    return Diagnostic(code=code, severity="error", message=message, path=path)


def _parse_model(model: type[_StrictModel], payload: Any, label: str) -> _StrictModel:
    try:
        parsed = model.model_validate(payload)
    except ValidationError as exc:
        diagnostics = [
            _diagnostic(
                DiagnosticCode.PRODUCT_CONTRACT_INVALID,
                str(item["msg"]),
                "$" + "".join(
                    f"[{part}]" if isinstance(part, int) else f".{part}"
                    for part in item["loc"]
                ),
            )
            for item in exc.errors(include_url=False)
        ]
        raise CanonicalBridgeError(diagnostics) from exc
    if content_digest(parsed) != getattr(parsed, "content_digest"):
        raise CanonicalBridgeError([
            _diagnostic(
                DiagnosticCode.PRODUCT_CONTRACT_INVALID,
                f"{label} content digest does not match canonical content.",
                "$.content_digest",
            )
        ])
    return parsed


def parse_product_adapter(payload: Any) -> ProductCanonicalAdapter:
    parsed = _parse_model(ProductCanonicalAdapter, payload, "Product adapter")
    assert isinstance(parsed, ProductCanonicalAdapter)
    return parsed


def parse_reviewed_needs(payload: Any) -> ReviewedCapabilityNeeds:
    parsed = _parse_model(ReviewedCapabilityNeeds, payload, "Reviewed needs")
    assert isinstance(parsed, ReviewedCapabilityNeeds)
    return parsed


def verify_reviewed_source_candidate(
    reviewed: ReviewedCapabilityNeeds,
    source_candidate: Any,
) -> None:
    """Bind review to the exact registry-blind candidate artifact without using its prose."""
    if (
        not isinstance(source_candidate, dict)
        or set(source_candidate) != {"schema_version", "candidates"}
        or source_candidate.get("schema_version") != "capability-needs@1.0.0"
        or not isinstance(source_candidate.get("candidates"), list)
    ):
        raise CanonicalBridgeError([
            _diagnostic(
                DiagnosticCode.PRODUCT_CONTRACT_INVALID,
                "Source candidate must be a parsed capability-needs@1.0.0 artifact.",
                "$.source_candidate",
            )
        ])
    actual = _digest(source_candidate)
    if reviewed.source_candidate_digest != actual:
        raise CanonicalBridgeError([
            _diagnostic(
                DiagnosticCode.PRODUCT_CONTRACT_INVALID,
                "Reviewed capability needs do not bind the exact source candidate artifact.",
                "$.source_candidate_digest",
            )
        ])


def _section_digest(value: Any) -> str:
    return _digest(value)


def _loss_section(name: str, value: Any, status: str, mappings: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "section": name,
        "source_digest": _section_digest(value),
        "status": status,
        "mappings": mappings,
    }


def _product_provenance(item: dict[str, Any], source_id: str) -> list[dict[str, Any]]:
    quote = item.get("source_quote")
    section = item.get("source_section_id")
    if not isinstance(quote, str) or not quote or not isinstance(section, str) or not section:
        raise CanonicalBridgeError([
            _diagnostic(
                DiagnosticCode.PRODUCT_PROVENANCE_LOSS,
                "Supported Product records require non-empty source_quote and source_section_id.",
            )
        ])
    return [{"source_id": source_id, "location": section, "note": quote}]


def _variable_type(data_type: str) -> str | None:
    return {
        "boolean": "bool",
        "integer": "int",
        "decimal": "decimal",
        "string": "string",
        "date": "string",
        "datetime": "string",
        "choice": "enum",
    }.get(data_type)


def adapt_product_logic(
    product_logic: Any,
    adapter: ProductCanonicalAdapter,
    local_registry: CHTLocalDataRegistry,
) -> BridgeResult:
    diagnostics: list[Diagnostic] = []
    if not isinstance(product_logic, dict):
        diagnostics.append(_diagnostic(DiagnosticCode.PRODUCT_CONTRACT_INVALID, "Product logic must be an object.", "$"))
        product_logic = {}
    root_fields = set(product_logic)
    expected = set(PRODUCT_SECTIONS)
    for missing in sorted(expected - root_fields):
        diagnostics.append(_diagnostic(DiagnosticCode.PRODUCT_CONTRACT_INVALID, f"Missing Product section '{missing}'.", f"$.{missing}"))
    for extra in sorted(root_fields - expected):
        diagnostics.append(_diagnostic(DiagnosticCode.PRODUCT_FIELD_UNSUPPORTED, f"Unknown Product section '{extra}'.", f"$.{extra}"))

    sections: list[dict[str, Any]] = []
    metadata_sources: list[dict[str, Any]] = [{"source_id": adapter.source_id}]
    ir: dict[str, Any] = {
        "metadata": {
            "ir_version": 1,
            "guideline_id": adapter.guideline_id,
            "compiler_version": RESOLUTION_RULE_VERSION,
            "sources": metadata_sources,
        },
        "variables": {},
        "constants": {},
        "predicates": {},
        "actions": {},
        "phrases": {},
        "decisions": {},
        "outputs": {},
        "invariants": {},
        "phrase_bindings": {},
    }

    empty_only = ("supply_list", "predicates", "modules", "phrase_bank")
    for name in empty_only:
        value = product_logic.get(name)
        mappings: list[dict[str, str]] = []
        if not isinstance(value, list):
            diagnostics.append(_diagnostic(DiagnosticCode.PRODUCT_CONTRACT_INVALID, f"{name} must be an array.", f"$.{name}"))
            status = "blocked"
        elif value:
            diagnostics.append(_diagnostic(
                DiagnosticCode.PRODUCT_FIELD_UNSUPPORTED,
                f"Adapter v1 cannot convert non-empty {name} without clinical inference.",
                f"$.{name}",
            ))
            status = "blocked"
        else:
            status = "mapped_empty"
            mappings.append({"source_path": f"$.{name}", "target_path": "$.metadata.sources"})
        sections.append(_loss_section(name, value, status, mappings))

    router = product_logic.get("router")
    router_mappings: list[dict[str, str]] = []
    if not isinstance(router, dict) or set(router) != {"rules"} or router.get("rules") != []:
        diagnostics.append(_diagnostic(
            DiagnosticCode.PRODUCT_FIELD_UNSUPPORTED,
            "Adapter v1 supports only router={rules: []}; routing rules require an explicit canonical authoring path.",
            "$.router",
        ))
        router_status = "blocked"
    else:
        router_status = "mapped_empty"
        router_mappings.append({"source_path": "$.router.rules", "target_path": "$.metadata.sources"})
    sections.append(_loss_section("router", router, router_status, router_mappings))

    integrative = product_logic.get("integrative")
    integrative_mappings: list[dict[str, str]] = []
    if (
        not isinstance(integrative, dict)
        or set(integrative) != {"description", "rules"}
        or not isinstance(integrative.get("description"), str)
        or not integrative.get("description")
        or integrative.get("rules") != []
    ):
        diagnostics.append(_diagnostic(
            DiagnosticCode.PRODUCT_FIELD_UNSUPPORTED,
            "Adapter v1 requires a non-empty integrative description and no integrative rules.",
            "$.integrative",
        ))
        integrative_status = "blocked"
    else:
        metadata_sources.append({
            "source_id": adapter.source_id,
            "kind": "product_integrative_description",
            "note": integrative["description"],
        })
        integrative_status = "mapped"
        integrative_mappings.extend([
            {"source_path": "$.integrative.description", "target_path": "$.metadata.sources[1].note"},
            {"source_path": "$.integrative.rules", "target_path": "$.metadata.sources"},
        ])
    sections.append(_loss_section("integrative", integrative, integrative_status, integrative_mappings))

    raw_variables = product_logic.get("variables")
    variable_mappings: list[dict[str, str]] = []
    allowed_variable_fields = {
        "id", "display_name", "kind", "unit", "data_type", "source_quote",
        "source_section_id", "allowed_missingness", "domain",
    }
    if not isinstance(raw_variables, list):
        diagnostics.append(_diagnostic(DiagnosticCode.PRODUCT_CONTRACT_INVALID, "variables must be an array.", "$.variables"))
    else:
        for index, raw in enumerate(raw_variables):
            path = f"$.variables[{index}]"
            if not isinstance(raw, dict):
                diagnostics.append(_diagnostic(DiagnosticCode.PRODUCT_CONTRACT_INVALID, "Variable must be an object.", path))
                continue
            if set(raw) != allowed_variable_fields:
                diagnostics.append(_diagnostic(
                    DiagnosticCode.PRODUCT_FIELD_UNSUPPORTED,
                    "Variable fields must exactly match the v1 adapter contract.",
                    path,
                ))
                continue
            identifier = raw["id"]
            if not isinstance(identifier, str) or not identifier.startswith(("v_", "h_", "st_")):
                diagnostics.append(_diagnostic(
                    DiagnosticCode.PRODUCT_FIELD_UNSUPPORTED,
                    "Product variable IDs must already use canonical v_, h_, or st_ prefixes; renaming is never inferred.",
                    f"{path}.id",
                ))
                continue
            if not isinstance(raw["display_name"], str) or not raw["display_name"]:
                diagnostics.append(_diagnostic(
                    DiagnosticCode.PRODUCT_CONTRACT_INVALID,
                    "Variable display_name must be a non-empty string.",
                    f"{path}.display_name",
                ))
                continue
            if type(raw["allowed_missingness"]) is not bool:
                diagnostics.append(_diagnostic(
                    DiagnosticCode.PRODUCT_CONTRACT_INVALID,
                    "Variable allowed_missingness must be a boolean.",
                    f"{path}.allowed_missingness",
                ))
                continue
            scalar_type = _variable_type(raw["data_type"])
            if scalar_type is None:
                diagnostics.append(_diagnostic(
                    DiagnosticCode.PRODUCT_FIELD_UNSUPPORTED,
                    f"Unsupported or ambiguous Product data_type '{raw['data_type']}'.",
                    f"{path}.data_type",
                ))
                continue
            kind_map = {"input": "encounter_input", "history": "history", "derived": "derived"}
            source_kind = kind_map.get(raw["kind"])
            if source_kind is None:
                diagnostics.append(_diagnostic(DiagnosticCode.PRODUCT_FIELD_UNSUPPORTED, "Unsupported variable kind.", f"{path}.kind"))
                continue
            unit = raw["unit"]
            if not isinstance(unit, str) or not unit:
                diagnostics.append(_diagnostic(
                    DiagnosticCode.PRODUCT_CONTRACT_INVALID,
                    "Variable unit must be explicit; use 'none' when unitless.",
                    f"{path}.unit",
                ))
                continue
            try:
                provenance = _product_provenance(raw, adapter.source_id)
            except CanonicalBridgeError as exc:
                diagnostics.extend(exc.diagnostics)
                continue
            variable: dict[str, Any] = {
                "type": scalar_type,
                "unit": None if unit == "none" else unit,
                "allowed_missingness": raw["allowed_missingness"],
                "multivalue": False,
                "source_kind": source_kind,
                "provenance": provenance,
            }
            if scalar_type == "enum":
                domain = raw["domain"]
                if not isinstance(domain, list) or not domain or not all(isinstance(item, str) and item for item in domain):
                    diagnostics.append(_diagnostic(
                        DiagnosticCode.PRODUCT_CONTRACT_INVALID,
                        "Choice variables require a non-empty string domain.",
                        f"{path}.domain",
                    ))
                    continue
                variable["domain"] = {"values": domain}
            elif raw["domain"] is not None:
                diagnostics.append(_diagnostic(
                    DiagnosticCode.PRODUCT_FIELD_UNSUPPORTED,
                    "Adapter v1 accepts domain only for choice variables.",
                    f"{path}.domain",
                ))
                continue
            if identifier in ir["variables"]:
                diagnostics.append(_diagnostic(DiagnosticCode.PRODUCT_CONTRACT_INVALID, "Duplicate variable ID.", f"{path}.id"))
                continue
            ir["variables"][identifier] = variable
            phrase_key = f"m_label_{identifier}"
            ir["phrases"][phrase_key] = {
                "entity_id": identifier,
                "role": "label",
                "texts": {"en": raw["display_name"]},
                "provenance": provenance,
            }
            for field in sorted(allowed_variable_fields):
                target = f"$.variables.{identifier}" if field != "display_name" else f"$.phrases.{phrase_key}"
                variable_mappings.append({"source_path": f"{path}.{field}", "target_path": target})

    read_by_target = {item.target_var: item for item in adapter.local_data_reads}
    recorded_at_targets = {
        item.recorded_at_target_var: item
        for item in adapter.local_data_reads
        if item.recorded_at_target_var is not None
    }
    for identifier, variable in ir["variables"].items():
        if variable["source_kind"] != "history":
            continue
        if identifier in recorded_at_targets:
            continue
        read = read_by_target.get(identifier)
        if read is None:
            diagnostics.append(_diagnostic(
                DiagnosticCode.PRODUCT_FIELD_UNSUPPORTED,
                f"History variable '{identifier}' has no reviewed local-data binding.",
                f"$.variables.{identifier}",
            ))
            continue
        binding = local_registry.bindings.get(read.binding_id)
        if binding is None:
            diagnostics.append(_diagnostic(
                DiagnosticCode.CHT_LOCAL_DATA_BINDING_UNBOUND,
                f"Local-data binding '{read.binding_id}' is not registered.",
                "$.local_data_reads",
            ))
            continue
        if variable["type"] != binding.value_type or variable.get("unit") != binding.unit:
            diagnostics.append(_diagnostic(
                DiagnosticCode.CHT_LOCAL_DATA_TYPE_MISMATCH,
                f"Local-data binding '{read.binding_id}' type/unit does not match '{identifier}'.",
                f"$.variables.{identifier}",
            ))
            continue
        variable["history_binding"] = {
            "record_key": read.binding_id,
            **({"freshness_max_age_days": binding.max_age_days} if binding.max_age_days is not None else {}),
        }
        outputs = [read.target_var]
        if read.recorded_at_target_var:
            recorded = ir["variables"].get(read.recorded_at_target_var)
            if recorded is None or recorded["source_kind"] != "history":
                diagnostics.append(_diagnostic(
                    DiagnosticCode.PRODUCT_CONTRACT_INVALID,
                    "recorded_at_target_var must reference a Product history variable.",
                    "$.local_data_reads",
                ))
                continue
            recorded["history_binding"] = {"record_key": read.binding_id}
            outputs.append(read.recorded_at_target_var)
        ir["actions"][read.action_id] = {
            "kind": "read_local_data",
            "source": read.binding_id,
            "outputs": outputs,
            "mappings": [{
                "record_key": "value",
                "target_var": read.target_var,
                **({"recorded_at_target_var": read.recorded_at_target_var} if read.recorded_at_target_var else {}),
            }],
            "fail_mode": read.fail_mode,
            "provenance": [{"source_id": adapter.source_id, "note": "reviewed local-data binding"}],
        }

    sections.append(_loss_section(
        "variables",
        raw_variables,
        "blocked" if any(item.path and item.path.startswith("$.variables") for item in diagnostics) else "mapped",
        variable_mappings,
    ))
    sections.sort(key=lambda item: PRODUCT_SECTIONS.index(item["section"]))
    loss_report = {
        "schema_version": LOSS_REPORT_SCHEMA_VERSION,
        "status": "blocked" if diagnostics else "complete",
        "product_content_digest": _digest(product_logic),
        "adapter_content_digest": adapter.content_digest,
        "sections": sections,
        "diagnostics": [
            {"code": str(item.code), "message": item.message, "path": item.path}
            for item in diagnostics
        ],
    }
    if diagnostics:
        return BridgeResult(canonical_ir=None, loss_report=loss_report)
    try:
        document = ClinicalIRDocument.from_dict(ir)
    except ValueError as exc:
        diagnostic = _diagnostic(DiagnosticCode.PRODUCT_CONTRACT_INVALID, str(exc), "$.canonical_ir")
        loss_report["status"] = "blocked"
        loss_report["diagnostics"].append({"code": str(diagnostic.code), "message": diagnostic.message, "path": diagnostic.path})
        return BridgeResult(canonical_ir=None, loss_report=loss_report)
    validation_errors = validate_document(document)
    if validation_errors:
        loss_report["status"] = "blocked"
        for item in validation_errors:
            loss_report["diagnostics"].append({
                "code": str(DiagnosticCode.PRODUCT_CONTRACT_INVALID),
                "message": item.message,
                "path": item.path,
            })
        return BridgeResult(canonical_ir=None, loss_report=loss_report)
    return BridgeResult(canonical_ir=deepcopy(ir), loss_report=loss_report)


def _capability_semantics(capability: Capability) -> dict[str, Any]:
    return {
        "family": capability.family,
        "operation": capability.operation,
        "inputs": [(item.name, item.type, item.unit) for item in capability.inputs],
        "outputs": [(item.name, item.type, item.unit) for item in capability.outputs],
        "statuses": sorted(capability.status_set),
        "target_profiles": sorted(capability.supported_target_profiles),
        "subject_scope": capability.subject_scope,
    }


def _need_semantics(need: ReviewedCapabilityNeed) -> dict[str, Any]:
    return {
        "family": need.family,
        "operation": need.operation,
        "inputs": [(item.name, item.type, item.unit) for item in need.inputs],
        "outputs": [(item.name, item.type, item.unit) for item in need.outputs],
        "statuses": sorted(need.required_statuses),
        "target_profile": need.target_profile,
        "subject_scope": need.subject_scope,
    }


def _is_exact_match(
    need: ReviewedCapabilityNeed,
    capability: Capability,
    registry: RegistrySetV2,
) -> bool:
    governance = {
        (item.capability_id, item.capability_version, item.capability_content_digest): item
        for item in registry.capability_governance.entries
    }
    governed = governance.get((capability.id, capability.version, capability.content_digest))
    expected = _need_semantics(need)
    actual = _capability_semantics(capability)
    return (
        governed is not None
        and governed.lifecycle_state == "approved"
        and expected["family"] == actual["family"]
        and expected["operation"] == actual["operation"]
        and expected["inputs"] == actual["inputs"]
        and expected["outputs"] == actual["outputs"]
        and expected["statuses"] == actual["statuses"]
        and expected["target_profile"] in actual["target_profiles"]
        and expected["subject_scope"] == actual["subject_scope"]
    )


def resolve_reviewed_needs(
    reviewed: ReviewedCapabilityNeeds,
    registry: RegistrySetV2,
    activated: ActivatedRegistryRelease,
    target_profile: TargetProfile,
) -> dict[str, Any]:
    # Re-establish content and schema invariants at the resolution boundary;
    # callers cannot bypass them with a preconstructed or mutated model.
    reviewed = parse_reviewed_needs(reviewed.model_dump(mode="json"))
    registry = parse_registry_set_v2(registry.model_dump(mode="json"))
    if activated.registry_set_digest != registry.content_digest:
        raise CanonicalBridgeError([
            _diagnostic(
                DiagnosticCode.REGISTRY_RELEASE_MISMATCH,
                "Activated release does not bind the exact governed registry set.",
                "$.activated_release.registry_set_digest",
            )
        ])
    if (
        target_profile.content_digest != registry.target_profile.content_digest
        or target_profile.model_dump(mode="json") != registry.target_profile.model_dump(mode="json")
    ):
        raise CanonicalBridgeError([
            _diagnostic(
                DiagnosticCode.REGISTRY_RELEASE_MISMATCH,
                "Supplied target profile is not the exact profile in the activated registry set.",
                "$.target_profile",
            )
        ])

    entries: list[dict[str, Any]] = []
    capabilities = sorted(
        registry.capability_registry.capabilities,
        key=lambda item: (item.id, item.version, item.content_digest),
    )
    for need in sorted(reviewed.needs, key=lambda item: item.need_id):
        matches = [item for item in capabilities if _is_exact_match(need, item, registry)]
        if not matches:
            same_operation = [
                item for item in capabilities
                if item.family == need.family and item.operation == need.operation
            ]
            if same_operation:
                raise CanonicalBridgeError([
                    _diagnostic(
                        DiagnosticCode.CAPABILITY_NEED_CONTRACT_MISMATCH,
                        f"Need '{need.need_id}' has the right family/operation but mismatches its exact typed contract.",
                        f"$.needs.{need.need_id}",
                    )
                ])
            raise CanonicalBridgeError([
                _diagnostic(
                    DiagnosticCode.CAPABILITY_NEED_UNRESOLVED,
                    f"Need '{need.need_id}' has no exact governed capability match.",
                    f"$.needs.{need.need_id}",
                )
            ])
        if len(matches) > 1:
            raise CanonicalBridgeError([
                _diagnostic(
                    DiagnosticCode.CAPABILITY_NEED_AMBIGUOUS,
                    f"Need '{need.need_id}' has multiple exact governed capability matches.",
                    f"$.needs.{need.need_id}",
                )
            ])
        capability = matches[0]
        entries.append({
            "need_id": need.need_id,
            "capability_id": capability.id,
            "capability_version": capability.version,
            "capability_content_digest": capability.content_digest,
            "registry_set_digest": registry.content_digest,
            "target_profile_digest": target_profile.content_digest,
            "release_digest": activated.release_digest,
            "resolution_rule_version": RESOLUTION_RULE_VERSION,
            "rationale": {
                "rule": "exact_equality_only",
                "matched_fields": list(RESOLUTION_MATCHED_FIELDS),
                "forbidden_selectors": list(RESOLUTION_FORBIDDEN_SELECTORS),
            },
        })
    lock = {
        "schema_version": RESOLUTION_LOCK_SCHEMA_VERSION,
        "content_digest": "sha256:" + "0" * 64,
        "registry_set_digest": registry.content_digest,
        "target_profile_digest": target_profile.content_digest,
        "release_digest": activated.release_digest,
        "resolution_rule_version": RESOLUTION_RULE_VERSION,
        "resolutions": entries,
    }
    return _seal(lock)


def _canonical_type(value_type: str) -> str:
    return {
        "boolean": "bool",
        "integer": "int",
        "decimal": "decimal",
        "string": "string",
        "date": "string",
        "datetime": "string",
        "choice": "enum",
    }[value_type]


def _validated_lock_resolutions(
    reviewed: ReviewedCapabilityNeeds,
    registry: RegistrySetV2,
    resolution_lock: Any,
) -> dict[str, dict[str, Any]]:
    root_fields = {
        "schema_version", "content_digest", "registry_set_digest",
        "target_profile_digest", "release_digest", "resolution_rule_version",
        "resolutions",
    }
    entry_fields = {
        "need_id", "capability_id", "capability_version",
        "capability_content_digest", "registry_set_digest",
        "target_profile_digest", "release_digest", "resolution_rule_version",
        "rationale",
    }
    rationale = {
        "rule": "exact_equality_only",
        "matched_fields": list(RESOLUTION_MATCHED_FIELDS),
        "forbidden_selectors": list(RESOLUTION_FORBIDDEN_SELECTORS),
    }
    invalid = (
        not isinstance(resolution_lock, dict)
        or set(resolution_lock) != root_fields
        or resolution_lock.get("schema_version") != RESOLUTION_LOCK_SCHEMA_VERSION
        or resolution_lock.get("resolution_rule_version") != RESOLUTION_RULE_VERSION
        or resolution_lock.get("content_digest") != content_digest(resolution_lock)
        or resolution_lock.get("registry_set_digest") != registry.content_digest
        or resolution_lock.get("target_profile_digest") != registry.target_profile.content_digest
        or not isinstance(resolution_lock.get("resolutions"), list)
    )
    if invalid:
        raise CanonicalBridgeError([
            _diagnostic(
                DiagnosticCode.PRODUCT_CONTRACT_INVALID,
                "Resolution lock is malformed, stale, or not bound to the exact registry set.",
                "$.resolution_lock",
            )
        ])

    capabilities = sorted(
        registry.capability_registry.capabilities,
        key=lambda item: (item.id, item.version, item.content_digest),
    )
    need_by_id = {item.need_id: item for item in reviewed.needs}
    entries: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(resolution_lock["resolutions"]):
        if not isinstance(entry, dict) or set(entry) != entry_fields:
            invalid = True
            break
        need = need_by_id.get(entry.get("need_id"))
        matches = [] if need is None else [
            item for item in capabilities if _is_exact_match(need, item, registry)
        ]
        selected = None if len(matches) != 1 else matches[0]
        if (
            need is None
            or entry["need_id"] in entries
            or selected is None
            or entry["capability_id"] != selected.id
            or entry["capability_version"] != selected.version
            or entry["capability_content_digest"] != selected.content_digest
            or entry["registry_set_digest"] != resolution_lock["registry_set_digest"]
            or entry["target_profile_digest"] != resolution_lock["target_profile_digest"]
            or entry["release_digest"] != resolution_lock["release_digest"]
            or entry["resolution_rule_version"] != RESOLUTION_RULE_VERSION
            or entry["rationale"] != rationale
        ):
            invalid = True
            break
        entries[entry["need_id"]] = entry
    if invalid or set(entries) != set(need_by_id):
        raise CanonicalBridgeError([
            _diagnostic(
                DiagnosticCode.PRODUCT_CONTRACT_INVALID,
                "Resolution lock does not reproduce the unique exact resolution for every reviewed need.",
                "$.resolution_lock.resolutions",
            )
        ])
    return entries


def _assert_variable_contract(
    ir: dict[str, Any],
    parameter: ReviewedParameterBinding,
    path: str,
) -> None:
    variable = ir["variables"].get(parameter.variable_id)
    expected_type = _canonical_type(parameter.type)
    expected_unit = None if parameter.unit == "none" else parameter.unit
    if variable is None or variable.get("type") != expected_type or variable.get("unit") != expected_unit:
        raise CanonicalBridgeError([
            _diagnostic(
                DiagnosticCode.CAPABILITY_NEED_CONTRACT_MISMATCH,
                f"Variable '{parameter.variable_id}' does not match {parameter.type} [{parameter.unit}].",
                path,
            )
        ])


def apply_resolution_to_ir(
    canonical_ir: dict[str, Any],
    reviewed: ReviewedCapabilityNeeds,
    registry: RegistrySetV2,
    resolution_lock: dict[str, Any],
) -> dict[str, Any]:
    reviewed = parse_reviewed_needs(reviewed.model_dump(mode="json"))
    registry = parse_registry_set_v2(registry.model_dump(mode="json"))
    resolutions = _validated_lock_resolutions(reviewed, registry, resolution_lock)
    ir = deepcopy(canonical_ir)
    capabilities = {
        (item.id, item.version, item.content_digest): item
        for item in registry.capability_registry.capabilities
    }
    for need in sorted(reviewed.needs, key=lambda item: item.need_id):
        resolution = resolutions[need.need_id]
        capability = capabilities[
            (
                resolution["capability_id"],
                resolution["capability_version"],
                resolution["capability_content_digest"],
            )
        ]
        for index, parameter in enumerate(need.inputs):
            _assert_variable_contract(ir, parameter, f"$.needs.{need.need_id}.inputs[{index}]")
        for index, parameter in enumerate(need.outputs):
            _assert_variable_contract(ir, parameter, f"$.needs.{need.need_id}.outputs[{index}]")
        status_variable = ir["variables"].get(need.status_target_var)
        if (
            status_variable is None
            or status_variable.get("type") != "enum"
            or status_variable.get("domain", {}).get("values") != list(capability.status_set)
        ):
            raise CanonicalBridgeError([
                _diagnostic(
                    DiagnosticCode.CAPABILITY_NEED_CONTRACT_MISMATCH,
                    "Status target must be an enum with the exact registered status order.",
                    f"$.variables.{need.status_target_var}",
                )
            ])
        suffix = need.need_id.removeprefix("need_")
        action_id = f"a_{suffix}"
        if action_id in ir["actions"]:
            raise CanonicalBridgeError([
                _diagnostic(
                    DiagnosticCode.CAPABILITY_NEED_CONTRACT_MISMATCH,
                    f"Generated capability action '{action_id}' collides with an existing action.",
                    f"$.actions.{action_id}",
                )
            ])
        provenance = [{
            "source_id": need.source["document_id"],
            "page": need.source["page"],
            "section": need.source["section"],
            "note": need.source["quote"],
        }]
        ir["actions"][action_id] = {
            "kind": "invoke_capability",
            "capability_id": capability.id,
            "arguments": {item.name: item.variable_id for item in need.inputs},
            "status_target_var": need.status_target_var,
            "outputs": [item.variable_id for item in need.outputs],
            "mappings": [
                {"record_key": item.name, "target_var": item.variable_id}
                for item in need.outputs
            ],
            "provenance": provenance,
        }
        usable_output = f"o_{suffix}_usable"
        decision_id = f"d_{suffix}_status"
        ir["outputs"][usable_output] = {
            "type": "bool",
            "description": "Technical capability status only; not a clinical decision output.",
            "provenance": provenance,
        }
        rules = []
        for index, status in enumerate(capability.status_set):
            rules.append({
                "id": f"r_{suffix}_{index:02d}_{status}",
                "when": {
                    "kind": "=",
                    "left": {"kind": "var", "id": need.status_target_var},
                    "right": {"kind": "literal", "type": "enum", "value": status},
                },
                "then": {
                    usable_output: {
                        "kind": "literal",
                        "type": "bool",
                        "value": status == "ok",
                    }
                },
                "provenance": provenance,
            })
        rules.append({
            "id": f"r_{suffix}_else",
            "when": {"kind": "else"},
            "then": {
                usable_output: {"kind": "literal", "type": "bool", "value": False}
            },
            "provenance": provenance,
        })
        ir["decisions"][decision_id] = {
            "hit_policy": "FIRST",
            "inputs_used": [need.status_target_var],
            "depends_on": [],
            "rules": rules,
            "provenance": provenance,
        }

    try:
        document = ClinicalIRDocument.from_dict(ir)
    except ValueError as exc:
        raise CanonicalBridgeError([
            _diagnostic(DiagnosticCode.CAPABILITY_NEED_CONTRACT_MISMATCH, str(exc), "$.canonical_ir")
        ]) from exc
    errors = validate_document(document)
    if errors:
        raise CanonicalBridgeError([
            _diagnostic(DiagnosticCode.CAPABILITY_NEED_CONTRACT_MISMATCH, item.message, item.path)
            for item in errors
        ])
    return ir


def apply_task_intents(
    canonical_ir: dict[str, Any],
    adapter: ProductCanonicalAdapter,
) -> dict[str, Any]:
    adapter = parse_product_adapter(adapter.model_dump(mode="json"))
    ir = deepcopy(canonical_ir)
    provenance = [{"source_id": adapter.source_id, "note": "reviewed synthetic task intent"}]
    for task in sorted(adapter.task_intents, key=lambda item: item.action_id):
        if task.action_id in ir["actions"]:
            raise CanonicalBridgeError([
                _diagnostic(
                    DiagnosticCode.PRODUCT_CONTRACT_INVALID,
                    f"Task action '{task.action_id}' collides with another action.",
                    f"$.actions.{task.action_id}",
                )
            ])
        if task.when_output not in ir["outputs"]:
            raise CanonicalBridgeError([
                _diagnostic(
                    DiagnosticCode.PRODUCT_CONTRACT_INVALID,
                    f"Task intent references unknown output '{task.when_output}'.",
                    "$.task_intents",
                )
            ])
        ir["phrases"][task.message_key] = {
            "entity_id": task.action_id,
            "role": "message",
            "texts": {"en": task.message_text},
            "provenance": provenance,
        }
        ir["actions"][task.action_id] = {
            "kind": "create_task",
            "outputs": [],
            "when": {"kind": "output", "id": task.when_output},
            "task_type": task.task_type,
            "due_in_days": task.due_in_days,
            "priority": task.priority,
            "assignee_role": task.assignee_role,
            "message_key": task.message_key,
            "provenance": provenance,
        }
    try:
        document = ClinicalIRDocument.from_dict(ir)
    except ValueError as exc:
        raise CanonicalBridgeError([
            _diagnostic(DiagnosticCode.PRODUCT_CONTRACT_INVALID, str(exc), "$.task_intents")
        ]) from exc
    errors = validate_document(document)
    if errors:
        raise CanonicalBridgeError([
            _diagnostic(DiagnosticCode.PRODUCT_CONTRACT_INVALID, item.message, item.path)
            for item in errors
        ])
    return ir


def build_ws5_package(
    product_logic: Any,
    source_candidate: Any,
    adapter: ProductCanonicalAdapter,
    local_registry: CHTLocalDataRegistry,
    reviewed: ReviewedCapabilityNeeds,
    registry: RegistrySetV2,
    activated: ActivatedRegistryRelease,
    target_profile: TargetProfile,
) -> WS5Package:
    adapter = parse_product_adapter(adapter.model_dump(mode="json"))
    verify_reviewed_source_candidate(reviewed, source_candidate)
    bridge = adapt_product_logic(product_logic, adapter, local_registry)
    if bridge.canonical_ir is None:
        diagnostics = [
            _diagnostic(DiagnosticCode(item["code"]), item["message"], item.get("path"))
            for item in bridge.loss_report["diagnostics"]
        ]
        raise CanonicalBridgeError(diagnostics)
    lock = resolve_reviewed_needs(reviewed, registry, activated, target_profile)
    resolved_ir = apply_resolution_to_ir(bridge.canonical_ir, reviewed, registry, lock)
    resolved_ir = apply_task_intents(resolved_ir, adapter)
    return WS5Package(
        canonical_ir=resolved_ir,
        loss_report=bridge.loss_report,
        resolution_lock=lock,
    )


def _load_json(path: str | Path) -> Any:
    source = Path(path)
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CanonicalBridgeError([
            _diagnostic(DiagnosticCode.PRODUCT_CONTRACT_INVALID, f"Could not load {source}: {exc}", str(source))
        ]) from exc


def write_ws5_package(
    *,
    product_logic_path: str | Path,
    source_candidate_path: str | Path,
    adapter_path: str | Path,
    local_data_bindings_path: str | Path,
    reviewed_needs_path: str | Path,
    registry_set_path: str | Path,
    activated_release_path: str | Path,
    target_profile_path: str | Path,
    output_dir: str | Path,
) -> WS5Package:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    adapter = parse_product_adapter(_load_json(adapter_path))
    reviewed = parse_reviewed_needs(_load_json(reviewed_needs_path))
    registry = load_registry_set_v2(registry_set_path)
    try:
        activated = ActivatedRegistryRelease.model_validate(_load_json(activated_release_path))
        target = TargetProfile.model_validate(_load_json(target_profile_path))
    except ValidationError as exc:
        raise CanonicalBridgeError([
            _diagnostic(DiagnosticCode.PRODUCT_CONTRACT_INVALID, str(exc), "$.ws5_input")
        ]) from exc
    local_registry = load_cht_local_data_registry(local_data_bindings_path)
    product_logic = _load_json(product_logic_path)
    source_candidate = _load_json(source_candidate_path)
    verify_reviewed_source_candidate(reviewed, source_candidate)
    bridge = adapt_product_logic(product_logic, adapter, local_registry)
    (output / "loss-report.json").write_text(
        json.dumps(bridge.loss_report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if bridge.canonical_ir is None:
        raise CanonicalBridgeError([
            _diagnostic(DiagnosticCode(item["code"]), item["message"], item.get("path"))
            for item in bridge.loss_report["diagnostics"]
        ])
    package = build_ws5_package(
        product_logic,
        source_candidate,
        adapter,
        local_registry,
        reviewed,
        registry,
        activated,
        target,
    )
    (output / "canonical-ir.json").write_text(
        json.dumps(package.canonical_ir, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "resolution-lock.json").write_text(
        json.dumps(package.resolution_lock, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return package
