from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .pydantic_models import (
    ClinicalIRDocumentModel,
    MetadataModel,
    PatientCaseModel,
    PhraseModel,
    PredicateModel,
    VariableModel,
)


class _StrictSchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VariableCatalogJSONModel(_StrictSchemaModel):
    variables: list[VariableModel]


class PredicateCatalogJSONModel(_StrictSchemaModel):
    predicates: list[PredicateModel]


class PhraseBankJSONModel(_StrictSchemaModel):
    phrases: list[PhraseModel]


class PatientCaseSuiteJSONModel(_StrictSchemaModel):
    cases: list[PatientCaseModel]


SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "clinical_ir": ClinicalIRDocumentModel,
    "metadata": MetadataModel,
    "variable_catalog_json": VariableCatalogJSONModel,
    "predicate_catalog_json": PredicateCatalogJSONModel,
    "phrase_bank_json": PhraseBankJSONModel,
    "patient_case": PatientCaseModel,
    "patient_case_suite": PatientCaseSuiteJSONModel,
}


def build_json_schema(name: str) -> dict[str, Any]:
    try:
        model = SCHEMA_MODELS[name]
    except KeyError as exc:
        supported = ", ".join(sorted(SCHEMA_MODELS))
        raise ValueError(f"unsupported schema name '{name}'; expected one of: {supported}") from exc
    return model.model_json_schema()


def write_json_schemas(output_dir: str | Path) -> dict[str, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for name in sorted(SCHEMA_MODELS):
        path = target / f"{name}.schema.json"
        path.write_text(json.dumps(build_json_schema(name), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written[name] = path
    return written
