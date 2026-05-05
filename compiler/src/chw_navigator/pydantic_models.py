from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


def _require_prefix(value: str, prefixes: tuple[str, ...], field_name: str) -> str:
    if not value.startswith(prefixes):
        joined = ", ".join(prefixes)
        raise ValueError(f"{field_name} must start with one of: {joined}")
    return value


def _is_history_id(value: str) -> bool:
    return value.startswith("h_") or value.endswith("_h")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProvenanceModel(StrictModel):
    source_id: str
    kind: str | None = None
    location: str | None = None
    row: int | str | None = None
    column: int | str | None = None
    table: str | None = None
    page: int | str | None = None
    section: str | None = None
    note: str | None = None


class DomainModel(StrictModel):
    min: int | float | None = None
    max: int | float | None = None
    values: list[str] | None = None

    @model_validator(mode="after")
    def validate_domain(self) -> "DomainModel":
        if self.values is None and self.min is None and self.max is None:
            raise ValueError("domain must define min/max or values")
        if self.values is not None and (self.min is not None or self.max is not None):
            raise ValueError("domain cannot mix values with min/max")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("domain min cannot exceed max")
        if self.values is not None and not self.values:
            raise ValueError("domain values cannot be empty")
        return self


ExpressionKind = Literal[
    "literal",
    "else",
    "var",
    "const",
    "pred",
    "output",
    "call",
    "and",
    "or",
    "exactly_one",
    "not",
    "if",
    "=",
    "!=",
    "<",
    "<=",
    ">",
    ">=",
    "+",
    "-",
    "*",
    "/",
    "selected",
]


class ExprModel(StrictModel):
    kind: ExpressionKind
    value: Any | None = None
    type: str | None = None
    id: str | None = None
    args: list[ExprModel] | None = None
    arg: ExprModel | None = None
    cond: ExprModel | None = None
    then: ExprModel | None = None
    else_: ExprModel | None = Field(default=None, alias="else")
    left: ExprModel | None = None
    right: ExprModel | None = None
    target: ExprModel | None = None
    choice: str | None = None
    fn: str | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "ExprModel":
        kind = self.kind
        if kind == "literal":
            return self
        if kind == "else":
            return self
        if kind == "var":
            if not self.id:
                raise ValueError("var expressions require id")
            _require_prefix(self.id, ("v_", "h_", "st_"), "expression var id")
            return self
        if kind == "const":
            if not self.id:
                raise ValueError("const expressions require id")
            _require_prefix(self.id, ("c_",), "expression const id")
            return self
        if kind == "pred":
            if not self.id:
                raise ValueError("pred expressions require id")
            _require_prefix(self.id, ("p_",), "expression pred id")
            return self
        if kind == "output":
            if not self.id:
                raise ValueError("output expressions require id")
            _require_prefix(self.id, ("o_",), "expression output id")
            return self
        if kind == "call":
            if not self.fn:
                raise ValueError("call expressions require fn")
            if not self.args:
                raise ValueError("call expressions require args")
            return self
        if kind in {"and", "or", "exactly_one"}:
            if not self.args or len(self.args) < 1:
                raise ValueError(f"{kind} requires a non-empty args list")
            return self
        if kind == "not":
            if self.arg is None:
                raise ValueError("not requires arg")
            return self
        if kind == "if":
            if self.cond is None or self.then is None or self.else_ is None:
                raise ValueError("if requires cond, then, and else")
            return self
        if kind in {"=", "!=", "<", "<=", ">", ">=", "+", "-", "*", "/"}:
            if self.left is None or self.right is None:
                raise ValueError(f"{kind} requires left and right")
            return self
        if kind == "selected":
            if self.target is None:
                raise ValueError("selected requires target")
            if not self.choice:
                raise ValueError("selected requires non-empty choice")
            return self
        return self


class HistoryBindingModel(StrictModel):
    record_key: str
    recorded_at_var: str | None = None
    freshness_max_age_days: int | None = None
    must_collect_fresh_when: ExprModel | None = None
    derivation_kind: str | None = None
    derivation_expr: ExprModel | None = None

    @field_validator("recorded_at_var")
    @classmethod
    def validate_recorded_at_var(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_prefix(value, ("v_", "h_", "st_"), "history recorded_at_var")

    @model_validator(mode="after")
    def validate_history_binding(self) -> "HistoryBindingModel":
        if self.freshness_max_age_days is not None and self.freshness_max_age_days < 0:
            raise ValueError("freshness_max_age_days cannot be negative")
        if (self.derivation_kind is None) != (self.derivation_expr is None):
            raise ValueError("derivation_kind and derivation_expr must be provided together")
        return self


class VariableModel(StrictModel):
    id: str
    type: Literal["bool", "int", "decimal", "string", "string_key", "enum"]
    domain: DomainModel | None = None
    unit: str | None = None
    allowed_missingness: bool = False
    multivalue: bool = False
    source_kind: Literal["encounter_input", "history", "state", "derived"] | None = None
    history_binding: HistoryBindingModel | None = None
    provenance: list[ProvenanceModel]

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _require_prefix(value, ("v_", "h_", "st_"), "variable id")

    @model_validator(mode="after")
    def validate_variable(self) -> "VariableModel":
        if self.type == "enum" and not (self.domain and self.domain.values):
            raise ValueError("enum variables must define non-empty domain.values")
        if self.source_kind == "encounter_input" and not self.id.startswith("v_"):
            raise ValueError("encounter_input variables must use v_ ids")
        if self.source_kind == "history" and not _is_history_id(self.id):
            raise ValueError("history variables must use legacy h_ ids or the newer _h suffix")
        if self.source_kind in {"state", "derived"} and not self.id.startswith("st_"):
            raise ValueError("state and derived variables must use st_ ids")
        if self.history_binding is not None and not _is_history_id(self.id):
            raise ValueError("history_binding is only supported on legacy h_ ids or variables with the _h suffix")
        if _is_history_id(self.id) and self.source_kind not in {None, "history"}:
            raise ValueError("history variables must declare source_kind='history' when source_kind is set")
        if self.source_kind == "history" and self.history_binding is None:
            raise ValueError("history variables must define history_binding metadata")
        return self


class ConstantModel(StrictModel):
    id: str
    type: Literal["bool", "int", "decimal", "string", "string_key", "enum"]
    value: Any
    provenance: list[ProvenanceModel]

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _require_prefix(value, ("c_",), "constant id")


class PredicateModel(StrictModel):
    id: str
    inputs_used: list[str]
    expression: ExprModel
    missingness_policy: Literal["require_inputs", "treat_missing_as_false", "propagate_unknown"]
    description: str | None = None
    provenance: list[ProvenanceModel]

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _require_prefix(value, ("p_",), "predicate id")

    @field_validator("inputs_used")
    @classmethod
    def validate_inputs_used(cls, values: list[str]) -> list[str]:
        for value in values:
            _require_prefix(value, ("v_", "st_"), "predicate inputs_used item")
        return values


class PhraseModel(StrictModel):
    key: str
    entity_id: str
    role: Literal["label", "hint", "message", "guidance"]
    texts: dict[str, str]
    provenance: list[ProvenanceModel]

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        return _require_prefix(value, ("m_",), "phrase key")

    @field_validator("entity_id")
    @classmethod
    def validate_entity_id(cls, value: str) -> str:
        return _require_prefix(value, ("v_", "h_", "st_", "p_", "o_", "d_", "a_"), "phrase entity_id")

    @field_validator("texts")
    @classmethod
    def validate_texts(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("phrase must include at least one language text")
        for language, text in value.items():
            if not language.strip():
                raise ValueError("phrase language keys cannot be empty")
            if not text.strip():
                raise ValueError("phrase text cannot be empty")
        return value


class RuleModel(StrictModel):
    id: str
    when: ExprModel
    then: dict[str, Any]
    description: str | None = None
    provenance: list[ProvenanceModel]

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not value.startswith("r"):
            raise ValueError("rule id must start with 'r'")
        return value


class DecisionModel(StrictModel):
    id: str
    hit_policy: Literal["FIRST"]
    rules: list[RuleModel]
    stage: int | None = None
    inputs_used: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    provenance: list[ProvenanceModel]

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _require_prefix(value, ("d_",), "decision id")

    @model_validator(mode="after")
    def validate_decision(self) -> "DecisionModel":
        if not self.rules:
            raise ValueError("decision must include at least one rule")
        return self

    @field_validator("inputs_used")
    @classmethod
    def validate_inputs_used(cls, values: list[str]) -> list[str]:
        for value in values:
            _require_prefix(value, ("p_", "st_", "c_", "o_"), "decision inputs_used item")
        return values

    @field_validator("depends_on")
    @classmethod
    def validate_depends_on(cls, values: list[str]) -> list[str]:
        for value in values:
            _require_prefix(value, ("d_",), "decision depends_on item")
        return values


class ActionMappingModel(StrictModel):
    record_key: str
    target_var: str
    recorded_at_target_var: str | None = None

    @field_validator("target_var")
    @classmethod
    def validate_target_var(cls, value: str) -> str:
        return _require_prefix(value, ("v_", "h_", "st_"), "action mapping target_var")

    @field_validator("recorded_at_target_var")
    @classmethod
    def validate_recorded_at_target_var(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_prefix(value, ("v_", "h_", "st_"), "action mapping recorded_at_target_var")


class ActionModel(StrictModel):
    id: str
    kind: Literal["read_history", "ask", "compute", "create_task"]
    outputs: list[str] = Field(default_factory=list)
    when: ExprModel | None = None
    source: str | None = None
    mappings: list[ActionMappingModel] = Field(default_factory=list)
    fail_mode: Literal["soft_missing", "hard_error"] | None = None
    expression: ExprModel | None = None
    task_type: str | None = None
    due_in_days: int | None = None
    due_at_expr: ExprModel | None = None
    priority: str | None = None
    assignee_role: str | None = None
    message_key: str | None = None
    provenance: list[ProvenanceModel]

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _require_prefix(value, ("a_",), "action id")

    @field_validator("message_key")
    @classmethod
    def validate_message_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_prefix(value, ("m_",), "action message_key")

    @model_validator(mode="after")
    def validate_action(self) -> "ActionModel":
        if self.kind == "read_history":
            if not self.source:
                raise ValueError("read_history actions require source")
            if not self.mappings:
                raise ValueError("read_history actions require mappings")
            for output_name in self.outputs:
                if not _is_history_id(output_name):
                    raise ValueError("read_history output target must use legacy h_ ids or the newer _h suffix")
        if self.kind == "compute" and self.expression is None:
            raise ValueError("compute actions require expression")
        if self.kind == "create_task" and self.task_type is None:
            raise ValueError("create_task actions require task_type")
        if self.due_in_days is not None and self.due_in_days < 0:
            raise ValueError("due_in_days cannot be negative")
        if self.due_in_days is not None and self.due_at_expr is not None:
            raise ValueError("create_task actions must not set both due_in_days and due_at_expr")
        return self


class OutputModel(StrictModel):
    id: str
    type: Literal["bool", "int", "decimal", "string", "string_key", "enum"]
    domain: DomainModel | None = None
    description: str | None = None
    provenance: list[ProvenanceModel]

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _require_prefix(value, ("o_",), "output id")

    @model_validator(mode="after")
    def validate_output(self) -> "OutputModel":
        if self.type == "enum" and not (self.domain and self.domain.values):
            raise ValueError("enum outputs must define non-empty domain.values")
        return self


class InvariantModel(StrictModel):
    id: str
    expression: ExprModel
    severity: str = "error"
    provenance: list[ProvenanceModel]

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _require_prefix(value, ("i_",), "invariant id")


class MetadataModel(StrictModel):
    ir_version: int
    guideline_id: str
    compiler_version: str | None = None
    generated_at: str | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)


class PhraseBindingModel(StrictModel):
    message_key: str | None = None
    guidance_key: str | None = None

    @field_validator("message_key", "guidance_key")
    @classmethod
    def validate_phrase_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_prefix(value, ("m_",), "phrase binding key")

    @model_validator(mode="after")
    def validate_binding(self) -> "PhraseBindingModel":
        if not self.message_key and not self.guidance_key:
            raise ValueError("phrase binding must define message_key or guidance_key")
        return self


class ClinicalIRDocumentModel(StrictModel):
    metadata: MetadataModel
    variables: dict[str, VariableModel] = Field(default_factory=dict)
    constants: dict[str, ConstantModel] = Field(default_factory=dict)
    predicates: dict[str, PredicateModel] = Field(default_factory=dict)
    actions: dict[str, ActionModel] = Field(default_factory=dict)
    phrases: dict[str, PhraseModel] = Field(default_factory=dict)
    decisions: dict[str, DecisionModel] = Field(default_factory=dict)
    outputs: dict[str, OutputModel] = Field(default_factory=dict)
    invariants: dict[str, InvariantModel] = Field(default_factory=dict)
    phrase_bindings: dict[str, PhraseBindingModel] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_embedded_ids(self) -> "ClinicalIRDocumentModel":
        self._check_keys_match("variables", self.variables)
        self._check_keys_match("constants", self.constants)
        self._check_keys_match("predicates", self.predicates)
        self._check_keys_match("actions", self.actions)
        self._check_keys_match("phrases", self.phrases, attr="key")
        self._check_keys_match("decisions", self.decisions)
        self._check_keys_match("outputs", self.outputs)
        self._check_keys_match("invariants", self.invariants)
        for output_id in self.phrase_bindings:
            _require_prefix(output_id, ("o_",), "phrase_bindings output id")
        return self

    def _check_keys_match(self, label: str, values: dict[str, Any], *, attr: str = "id") -> None:
        for key, item in values.items():
            if getattr(item, attr) != key:
                raise ValueError(f"{label}.{key} key must match embedded {attr}")


ExprModel.model_rebuild()


def validate_ir_payload(data: dict[str, Any]) -> dict[str, Any]:
    model = ClinicalIRDocumentModel.model_validate(_normalize_ir_payload(data))
    return model.model_dump(by_alias=True)


def validate_variable_payload(data: dict[str, Any]) -> None:
    VariableModel.model_validate(data)


def validate_predicate_payload(data: dict[str, Any]) -> None:
    PredicateModel.model_validate(data)


def validate_phrase_payload(data: dict[str, Any]) -> None:
    PhraseModel.model_validate(data)


def validate_metadata_payload(data: dict[str, Any]) -> None:
    MetadataModel.model_validate(data)


def format_pydantic_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error.get("loc", ()))
        if location:
            parts.append(f"{location}: {error['msg']}")
        else:
            parts.append(error["msg"])
    return "; ".join(parts)


def _normalize_ir_payload(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    for section_name, id_field in (
        ("variables", "id"),
        ("constants", "id"),
        ("predicates", "id"),
        ("actions", "id"),
        ("phrases", "key"),
        ("decisions", "id"),
        ("outputs", "id"),
        ("invariants", "id"),
    ):
        section = normalized.get(section_name)
        if not isinstance(section, dict):
            continue
        normalized_section: dict[str, Any] = {}
        for key, value in section.items():
            if isinstance(value, dict) and id_field not in value:
                item = dict(value)
                item[id_field] = key
                normalized_section[key] = item
            else:
                normalized_section[key] = value
        normalized[section_name] = normalized_section
    return normalized
