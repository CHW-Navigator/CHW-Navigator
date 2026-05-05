from __future__ import annotations

from typing import Literal

from pydantic import Field, ValidationError, model_validator

from .pydantic_models import StrictModel


class ChangeMemoMetadataModel(StrictModel):
    memo_version: int
    change_id: str
    title: str
    change_type: Literal[
        "add_module",
        "modify_module",
        "add_option",
        "retire_rule",
        "add_commodity",
        "add_test",
        "modify_context",
    ]
    effective_date: str
    applies_to: list[str] = Field(default_factory=list)
    source_provenance: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_metadata(self) -> "ChangeMemoMetadataModel":
        if not self.applies_to:
            raise ValueError("applies_to must not be empty")
        if not self.source_provenance:
            raise ValueError("source_provenance must not be empty")
        return self


class ChangeMemoModel(StrictModel):
    metadata: ChangeMemoMetadataModel
    clinical_intent: str
    new_or_changed_inputs: list[str] = Field(default_factory=list)
    new_predicates_needed: list[str] = Field(default_factory=list)
    changed_classifications: list[str] = Field(default_factory=list)
    changed_actions: list[str] = Field(default_factory=list)
    priority_rules: list[str] = Field(default_factory=list)
    missingness_rules: list[str] = Field(default_factory=list)
    stockout_device_rules: list[str] = Field(default_factory=list)
    safety_invariants: list[str] = Field(default_factory=list)
    counseling_messages: list[str] = Field(default_factory=list)
    follow_up: list[str] = Field(default_factory=list)
    data_capture_reporting: list[str] = Field(default_factory=list)
    sunset_review_condition: str
    unresolved_questions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_memo(self) -> "ChangeMemoModel":
        if not self.clinical_intent.strip():
            raise ValueError("clinical_intent must not be empty")
        if not self.safety_invariants:
            raise ValueError("safety_invariants must not be empty")
        if not self.priority_rules:
            raise ValueError("priority_rules must not be empty")
        if not self.missingness_rules:
            raise ValueError("missingness_rules must not be empty")
        if not self.sunset_review_condition.strip():
            raise ValueError("sunset_review_condition must not be empty")
        return self


def validate_change_memo_payload(data: dict[str, object]) -> dict[str, object]:
    model = ChangeMemoModel.model_validate(data)
    return model.model_dump()


def format_change_memo_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error.get("loc", ()))
        if location:
            parts.append(f"{location}: {error['msg']}")
        else:
            parts.append(error["msg"])
    return "; ".join(parts)
