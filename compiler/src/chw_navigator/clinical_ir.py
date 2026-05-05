from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


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
class VariableDef:
    id: str
    type: ScalarType
    domain: Domain | None = None
    unit: str | None = None
    allowed_missingness: bool = False
    multivalue: bool = False
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
    phrases: dict[str, PhraseDef] = field(default_factory=dict)
    decisions: dict[str, DecisionDef] = field(default_factory=dict)
    outputs: dict[str, OutputDef] = field(default_factory=dict)
    invariants: dict[str, InvariantDef] = field(default_factory=dict)
    phrase_bindings: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClinicalIRDocument":
        return cls(
            metadata=_parse_metadata(data["metadata"]),
            variables={
                key: _parse_variable(key, value)
                for key, value in data.get("variables", {}).items()
            },
            constants={
                key: _parse_constant(key, value)
                for key, value in data.get("constants", {}).items()
            },
            predicates={
                key: _parse_predicate(key, value)
                for key, value in data.get("predicates", {}).items()
            },
            phrases={
                key: _parse_phrase(key, value)
                for key, value in data.get("phrases", {}).items()
            },
            decisions={
                key: _parse_decision(key, value)
                for key, value in data.get("decisions", {}).items()
            },
            outputs={
                key: _parse_output(key, value)
                for key, value in data.get("outputs", {}).items()
            },
            invariants={
                key: _parse_invariant(key, value)
                for key, value in data.get("invariants", {}).items()
            },
            phrase_bindings=dict(data.get("phrase_bindings", {})),
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
        rules=[_parse_rule(item) for item in data.get("rules", [])],
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
