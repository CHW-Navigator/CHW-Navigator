from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from .pydantic_models import format_pydantic_error, validate_ir_payload

class ScalarType(StrEnum):
    BOOL = "bool"
    INT = "int"
    DECIMAL = "decimal"
    STRING = "string"
    STRING_KEY = "string_key"
    ENUM = "enum"


class HitPolicy(StrEnum):
    FIRST = "FIRST"


class MissingnessPolicy(StrEnum):
    REQUIRE_INPUTS = "require_inputs"
    TREAT_MISSING_AS_FALSE = "treat_missing_as_false"
    PROPAGATE_UNKNOWN = "propagate_unknown"


class PhraseRole(StrEnum):
    LABEL = "label"
    HINT = "hint"
    MESSAGE = "message"
    GUIDANCE = "guidance"


class SourceKind(StrEnum):
    ENCOUNTER_INPUT = "encounter_input"
    HISTORY = "history"
    STATE = "state"
    DERIVED = "derived"


@dataclass(slots=True)
class ProvenanceRecord:
    source_id: str
    kind: str | None = None
    location: str | None = None
    row: int | None = None
    column: str | None = None
    table: str | None = None
    page: int | None = None
    section: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"source_id": self.source_id}
        for field_name in ("kind", "location", "row", "column", "table", "page", "section", "note"):
            value = getattr(self, field_name)
            if value is not None:
                data[field_name] = value
        return data


@dataclass(slots=True)
class Domain:
    min: int | float | None = None
    max: int | float | None = None
    values: list[str] | None = None


@dataclass(slots=True)
class HistoryBinding:
    record_key: str
    recorded_at_var: str | None = None
    freshness_max_age_days: int | None = None
    must_collect_fresh_when: dict[str, Any] | None = None
    derivation_kind: str | None = None
    derivation_expr: dict[str, Any] | None = None


@dataclass(slots=True)
class VariableDef:
    id: str
    type: ScalarType
    domain: Domain | None = None
    unit: str | None = None
    allowed_missingness: bool = False
    multivalue: bool = False
    source_kind: SourceKind | None = None
    history_binding: HistoryBinding | None = None
    provenance: list[ProvenanceRecord] = field(default_factory=list)


@dataclass(slots=True)
class ConstantDef:
    id: str
    type: ScalarType
    value: Any
    provenance: list[ProvenanceRecord] = field(default_factory=list)


@dataclass(slots=True)
class PredicateDef:
    id: str
    inputs_used: list[str]
    expression: dict[str, Any]
    missingness_policy: MissingnessPolicy
    description: str | None = None
    provenance: list[ProvenanceRecord] = field(default_factory=list)


@dataclass(slots=True)
class PhraseDef:
    key: str
    entity_id: str
    role: PhraseRole
    texts: dict[str, str]
    provenance: list[ProvenanceRecord] = field(default_factory=list)


@dataclass(slots=True)
class RuleDef:
    id: str
    when: dict[str, Any]
    then: dict[str, Any]
    description: str | None = None
    provenance: list[ProvenanceRecord] = field(default_factory=list)


@dataclass(slots=True)
class DecisionDef:
    id: str
    hit_policy: HitPolicy
    rules: list[RuleDef]
    stage: int | None = None
    inputs_used: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    provenance: list[ProvenanceRecord] = field(default_factory=list)


@dataclass(slots=True)
class ActionMappingDef:
    record_key: str
    target_var: str
    recorded_at_target_var: str | None = None


@dataclass(slots=True)
class ActionDef:
    id: str
    kind: str
    outputs: list[str] = field(default_factory=list)
    when: dict[str, Any] | None = None
    source: str | None = None
    mappings: list[ActionMappingDef] = field(default_factory=list)
    fail_mode: str | None = None
    expression: dict[str, Any] | None = None
    task_type: str | None = None
    due_in_days: int | None = None
    due_at_expr: dict[str, Any] | None = None
    priority: str | None = None
    assignee_role: str | None = None
    message_key: str | None = None
    provenance: list[ProvenanceRecord] = field(default_factory=list)


@dataclass(slots=True)
class OutputDef:
    id: str
    type: ScalarType
    domain: Domain | None = None
    description: str | None = None
    provenance: list[ProvenanceRecord] = field(default_factory=list)


@dataclass(slots=True)
class InvariantDef:
    id: str
    expression: dict[str, Any]
    severity: str = "error"
    provenance: list[ProvenanceRecord] = field(default_factory=list)


@dataclass(slots=True)
class Metadata:
    ir_version: int
    guideline_id: str
    compiler_version: str | None = None
    generated_at: str | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ClinicalIRDocument:
    metadata: Metadata
    variables: dict[str, VariableDef] = field(default_factory=dict)
    constants: dict[str, ConstantDef] = field(default_factory=dict)
    predicates: dict[str, PredicateDef] = field(default_factory=dict)
    actions: dict[str, ActionDef] = field(default_factory=dict)
    phrases: dict[str, PhraseDef] = field(default_factory=dict)
    decisions: dict[str, DecisionDef] = field(default_factory=dict)
    outputs: dict[str, OutputDef] = field(default_factory=dict)
    invariants: dict[str, InvariantDef] = field(default_factory=dict)
    phrase_bindings: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClinicalIRDocument":
        try:
            normalized = validate_ir_payload(data)
        except PydanticValidationError as exc:
            raise ValueError(format_pydantic_error(exc)) from exc
        return cls(
            metadata=_parse_metadata(normalized["metadata"]),
            variables={
                key: _parse_variable(key, value)
                for key, value in normalized.get("variables", {}).items()
            },
            constants={
                key: _parse_constant(key, value)
                for key, value in normalized.get("constants", {}).items()
            },
            predicates={
                key: _parse_predicate(key, value)
                for key, value in normalized.get("predicates", {}).items()
            },
            actions={
                key: _parse_action(key, value)
                for key, value in normalized.get("actions", {}).items()
            },
            phrases={
                key: _parse_phrase(key, value)
                for key, value in normalized.get("phrases", {}).items()
            },
            decisions={
                key: _parse_decision(key, value)
                for key, value in normalized.get("decisions", {}).items()
            },
            outputs={
                key: _parse_output(key, value)
                for key, value in normalized.get("outputs", {}).items()
            },
            invariants={
                key: _parse_invariant(key, value)
                for key, value in normalized.get("invariants", {}).items()
            },
            phrase_bindings={
                key: dict(value)
                for key, value in normalized.get("phrase_bindings", {}).items()
            },
        )


def _parse_metadata(data: dict[str, Any]) -> Metadata:
    return Metadata(
        ir_version=int(data["ir_version"]),
        guideline_id=str(data["guideline_id"]),
        compiler_version=data.get("compiler_version"),
        generated_at=data.get("generated_at"),
        sources=list(data.get("sources", [])),
    )


def _parse_variable(identifier: str, data: dict[str, Any]) -> VariableDef:
    return VariableDef(
        id=identifier,
        type=ScalarType(data["type"]),
        domain=_parse_domain(data.get("domain")),
        unit=data.get("unit"),
        allowed_missingness=bool(data.get("allowed_missingness", False)),
        multivalue=bool(data.get("multivalue", False)),
        source_kind=SourceKind(data["source_kind"]) if data.get("source_kind") else None,
        history_binding=_parse_history_binding(data.get("history_binding")),
        provenance=_parse_provenance(data.get("provenance", [])),
    )


def _parse_constant(identifier: str, data: dict[str, Any]) -> ConstantDef:
    return ConstantDef(
        id=identifier,
        type=ScalarType(data["type"]),
        value=data["value"],
        provenance=_parse_provenance(data.get("provenance", [])),
    )


def _parse_predicate(identifier: str, data: dict[str, Any]) -> PredicateDef:
    return PredicateDef(
        id=identifier,
        inputs_used=list(data.get("inputs_used", [])),
        expression=dict(data["expression"]),
        missingness_policy=MissingnessPolicy(data["missingness_policy"]),
        description=data.get("description"),
        provenance=_parse_provenance(data.get("provenance", [])),
    )


def _parse_rule(data: dict[str, Any]) -> RuleDef:
    return RuleDef(
        id=str(data["id"]),
        when=dict(data["when"]),
        then=dict(data.get("then", {})),
        description=data.get("description"),
        provenance=_parse_provenance(data.get("provenance", [])),
    )


def _parse_phrase(identifier: str, data: dict[str, Any]) -> PhraseDef:
    return PhraseDef(
        key=identifier,
        entity_id=str(data["entity_id"]),
        role=PhraseRole(data["role"]),
        texts={str(key): str(value) for key, value in dict(data.get("texts", {})).items()},
        provenance=_parse_provenance(data.get("provenance", [])),
    )


def _parse_decision(identifier: str, data: dict[str, Any]) -> DecisionDef:
    return DecisionDef(
        id=identifier,
        hit_policy=HitPolicy(data["hit_policy"]),
        stage=int(data["stage"]) if data.get("stage") is not None else None,
        inputs_used=[str(item) for item in data.get("inputs_used", [])],
        depends_on=[str(item) for item in data.get("depends_on", [])],
        rules=[_parse_rule(item) for item in data.get("rules", [])],
        provenance=_parse_provenance(data.get("provenance", [])),
    )


def _parse_action(identifier: str, data: dict[str, Any]) -> ActionDef:
    return ActionDef(
        id=identifier,
        kind=str(data["kind"]),
        outputs=[str(item) for item in data.get("outputs", [])],
        when=dict(data["when"]) if isinstance(data.get("when"), dict) else None,
        source=str(data["source"]) if data.get("source") is not None else None,
        mappings=[_parse_action_mapping(item) for item in data.get("mappings", [])],
        fail_mode=str(data["fail_mode"]) if data.get("fail_mode") is not None else None,
        expression=dict(data["expression"]) if isinstance(data.get("expression"), dict) else None,
        task_type=str(data["task_type"]) if data.get("task_type") is not None else None,
        due_in_days=int(data["due_in_days"]) if data.get("due_in_days") is not None else None,
        due_at_expr=dict(data["due_at_expr"]) if isinstance(data.get("due_at_expr"), dict) else None,
        priority=str(data["priority"]) if data.get("priority") is not None else None,
        assignee_role=str(data["assignee_role"]) if data.get("assignee_role") is not None else None,
        message_key=str(data["message_key"]) if data.get("message_key") is not None else None,
        provenance=_parse_provenance(data.get("provenance", [])),
    )


def _parse_output(identifier: str, data: dict[str, Any]) -> OutputDef:
    return OutputDef(
        id=identifier,
        type=ScalarType(data["type"]),
        domain=_parse_domain(data.get("domain")),
        description=data.get("description"),
        provenance=_parse_provenance(data.get("provenance", [])),
    )


def _parse_invariant(identifier: str, data: dict[str, Any]) -> InvariantDef:
    return InvariantDef(
        id=identifier,
        expression=dict(data["expression"]),
        severity=str(data.get("severity", "error")),
        provenance=_parse_provenance(data.get("provenance", [])),
    )


def _parse_domain(data: dict[str, Any] | list[str] | None) -> Domain | None:
    if data is None:
        return None
    if isinstance(data, list):
        return Domain(values=[str(item) for item in data])
    return Domain(
        min=data.get("min"),
        max=data.get("max"),
        values=(
            [str(item) for item in data["values"]]
            if "values" in data and data["values"] is not None
            else None
        ),
    )


def _parse_history_binding(data: dict[str, Any] | None) -> HistoryBinding | None:
    if data is None:
        return None
    return HistoryBinding(
        record_key=str(data["record_key"]),
        recorded_at_var=str(data["recorded_at_var"]) if data.get("recorded_at_var") is not None else None,
        freshness_max_age_days=int(data["freshness_max_age_days"]) if data.get("freshness_max_age_days") is not None else None,
        must_collect_fresh_when=dict(data["must_collect_fresh_when"]) if isinstance(data.get("must_collect_fresh_when"), dict) else None,
        derivation_kind=str(data["derivation_kind"]) if data.get("derivation_kind") is not None else None,
        derivation_expr=dict(data["derivation_expr"]) if isinstance(data.get("derivation_expr"), dict) else None,
    )


def _parse_action_mapping(data: dict[str, Any]) -> ActionMappingDef:
    return ActionMappingDef(
        record_key=str(data["record_key"]),
        target_var=str(data["target_var"]),
        recorded_at_target_var=(
            str(data["recorded_at_target_var"])
            if data.get("recorded_at_target_var") is not None
            else None
        ),
    )


def _parse_provenance(records: list[dict[str, Any]]) -> list[ProvenanceRecord]:
    return [
        ProvenanceRecord(
            source_id=str(item["source_id"]),
            kind=item.get("kind"),
            location=item.get("location"),
            row=item.get("row"),
            column=item.get("column"),
            table=item.get("table"),
            page=item.get("page"),
            section=item.get("section"),
            note=item.get("note"),
        )
        for item in records
    ]
