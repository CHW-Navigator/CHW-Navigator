from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from .clinical_ir import (
    ClinicalIRDocument,
    Domain,
    Metadata,
    MissingnessPolicy,
    PhraseDef,
    PhraseRole,
    PredicateDef,
    ProvenanceRecord,
    ScalarType,
    VariableDef,
)
from .pydantic_models import (
    format_pydantic_error,
    validate_metadata_payload,
    validate_phrase_payload,
    validate_predicate_payload,
    validate_variable_payload,
)
from .lint import lint_document
from .validator import validate_document


class CatalogLoadError(Exception):
    """Raised when a standalone catalog file cannot be loaded or normalized."""


@dataclass(slots=True)
class CatalogBundle:
    metadata: Metadata
    variables: dict[str, VariableDef]
    predicates: dict[str, PredicateDef]
    phrases: dict[str, PhraseDef]

    def to_document(self) -> ClinicalIRDocument:
        document = ClinicalIRDocument(
            metadata=self.metadata,
            variables=self.variables,
            predicates=self.predicates,
            phrases=self.phrases,
        )
        errors = validate_document(document)
        lint_issues = lint_document(document)
        if errors:
            message = "; ".join(f"{item.path}: {item.message}" for item in errors)
            raise CatalogLoadError(f"catalogs do not compose into a valid Clinical IR base document: {message}")
        lint_errors = [item for item in lint_issues if item.level == "ERROR"]
        if lint_errors:
            message = "; ".join(f"{item.path}: {item.message}" for item in lint_errors)
            raise CatalogLoadError(f"catalogs do not pass lint checks: {message}")
        return document


def compose_document_from_catalogs(
    metadata_path: str | Path,
    variable_catalog_path: str | Path,
    predicate_catalog_path: str | Path,
    phrase_bank_path: str | Path,
) -> ClinicalIRDocument:
    bundle = load_catalog_bundle(
        metadata_path=metadata_path,
        variable_catalog_path=variable_catalog_path,
        predicate_catalog_path=predicate_catalog_path,
        phrase_bank_path=phrase_bank_path,
    )
    return bundle.to_document()


def load_catalog_bundle(
    metadata_path: str | Path,
    variable_catalog_path: str | Path,
    predicate_catalog_path: str | Path,
    phrase_bank_path: str | Path,
) -> CatalogBundle:
    metadata = _load_metadata(Path(metadata_path))
    variables = load_variable_catalog(Path(variable_catalog_path))
    predicates = load_predicate_catalog(Path(predicate_catalog_path))
    phrases = load_phrase_bank(Path(phrase_bank_path))
    return CatalogBundle(metadata=metadata, variables=variables, predicates=predicates, phrases=phrases)


def load_variable_catalog(path: Path) -> dict[str, VariableDef]:
    rows = _load_records(path, "variable catalog", "variables")
    variables: dict[str, VariableDef] = {}
    for index, row in enumerate(rows):
        row_label = f"{path.name} row {index + 1}"
        variable_id = _required_string(row, "id", row_label)
        if variable_id in variables:
            raise CatalogLoadError(f"{row_label}: duplicate variable id '{variable_id}'")
        payload = {
            "id": variable_id,
            "type": _required_string(row, "type", row_label),
            "domain": _domain_to_payload(_parse_domain_row(row, row_label)),
            "unit": _optional_string(row, "unit"),
            "storage_unit": _optional_string(row, "storage_unit"),
            "input_decimals": row.get("input_decimals"),
            "display_decimals": row.get("display_decimals"),
            "remeasure_min": row.get("remeasure_min"),
            "remeasure_max": row.get("remeasure_max"),
            "dont_allow_min": row.get("dont_allow_min"),
            "dont_allow_max": row.get("dont_allow_max"),
            "measurement_limits": _parse_optional_json_object(
                row.get("measurement_limits"),
                f"{row_label}.measurement_limits",
            ),
            "allowed_missingness": _parse_bool(row.get("allowed_missingness", False), f"{row_label}.allowed_missingness"),
            "multivalue": _parse_bool(row.get("multivalue", False), f"{row_label}.multivalue"),
            "provenance": [_provenance_to_payload(item) for item in _parse_provenance_field(row, row_label)],
        }
        try:
            validate_variable_payload(payload)
        except PydanticValidationError as exc:
            raise CatalogLoadError(f"{row_label}: {format_pydantic_error(exc)}") from exc
        variables[variable_id] = VariableDef(
            id=variable_id,
            type=ScalarType(payload["type"]),
            domain=_parse_domain_row(row, row_label),
            unit=payload["unit"],
            allowed_missingness=payload["allowed_missingness"],
            multivalue=payload["multivalue"],
            provenance=_parse_provenance_field(row, row_label),
        )
    return variables


def load_predicate_catalog(path: Path) -> dict[str, PredicateDef]:
    rows = _load_records(path, "predicate catalog", "predicates")
    predicates: dict[str, PredicateDef] = {}
    for index, row in enumerate(rows):
        row_label = f"{path.name} row {index + 1}"
        predicate_id = _required_string(row, "id", row_label)
        if predicate_id in predicates:
            raise CatalogLoadError(f"{row_label}: duplicate predicate id '{predicate_id}'")
        payload = {
            "id": predicate_id,
            "inputs_used": _parse_string_list(
                row.get("inputs_used"),
                f"{row_label}.inputs_used",
            ),
            "expression": _parse_expression(
                row.get("expression", row.get("expression_json")),
                f"{row_label}.expression",
            ),
            "missingness_policy": _required_string(row, "missingness_policy", row_label),
            "description": _optional_string(row, "description"),
            "provenance": [_provenance_to_payload(item) for item in _parse_provenance_field(row, row_label)],
        }
        try:
            validate_predicate_payload(payload)
        except PydanticValidationError as exc:
            raise CatalogLoadError(f"{row_label}: {format_pydantic_error(exc)}") from exc
        predicates[predicate_id] = PredicateDef(
            id=predicate_id,
            inputs_used=payload["inputs_used"],
            expression=payload["expression"],
            missingness_policy=MissingnessPolicy(payload["missingness_policy"]),
            description=payload["description"],
            provenance=_parse_provenance_field(row, row_label),
        )
    return predicates


def load_phrase_bank(path: Path) -> dict[str, PhraseDef]:
    rows = _load_records(path, "phrase bank", "phrases")
    phrases: dict[str, PhraseDef] = {}
    for index, row in enumerate(rows):
        row_label = f"{path.name} row {index + 1}"
        key = _required_string(row, "key", row_label)
        if key in phrases:
            raise CatalogLoadError(f"{row_label}: duplicate phrase key '{key}'")
        entity_id = _optional_string(row, "entity_id") or _optional_string(row, "variable_name")
        if not entity_id:
            raise CatalogLoadError(f"{row_label}: phrase bank row must include entity_id or variable_name")
        texts = _parse_phrase_texts(row, row_label)
        payload = {
            "key": key,
            "entity_id": entity_id,
            "role": _required_string(row, "role", row_label),
            "texts": texts,
            "provenance": [_provenance_to_payload(item) for item in _parse_provenance_field(row, row_label)],
        }
        try:
            validate_phrase_payload(payload)
        except PydanticValidationError as exc:
            raise CatalogLoadError(f"{row_label}: {format_pydantic_error(exc)}") from exc
        phrases[key] = PhraseDef(
            key=key,
            entity_id=entity_id,
            role=PhraseRole(payload["role"]),
            texts=texts,
            provenance=_parse_provenance_field(row, row_label),
        )
    return phrases


def _load_metadata(path: Path) -> Metadata:
    data = _load_json(path, "metadata file")
    payload = dict(data.get("metadata", data))
    try:
        validate_metadata_payload(payload)
        return Metadata(
            ir_version=int(payload["ir_version"]),
            guideline_id=str(payload["guideline_id"]),
            compiler_version=payload.get("compiler_version"),
            generated_at=payload.get("generated_at"),
            sources=list(payload.get("sources", [])),
        )
    except PydanticValidationError as exc:
        raise CatalogLoadError(f"metadata file '{path}' is invalid: {format_pydantic_error(exc)}") from exc
    except KeyError as exc:
        raise CatalogLoadError(f"metadata file '{path}' is missing required key '{exc.args[0]}'") from exc


def _load_records(path: Path, label: str, list_key: str) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        data = _load_json(path, label)
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = data.get(list_key, data.get("items"))
        else:
            rows = None
        if not isinstance(rows, list):
            raise CatalogLoadError(f"{label} '{path}' must contain a top-level list or a '{list_key}' list")
        return [_coerce_record(item, f"{label} '{path}'") for item in rows]
    if path.suffix.lower() == ".csv":
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                return [dict(row) for row in csv.DictReader(handle)]
        except FileNotFoundError as exc:
            raise CatalogLoadError(f"{label} '{path}' not found") from exc
        except OSError as exc:
            raise CatalogLoadError(f"could not read {label} '{path}': {exc}") from exc
    raise CatalogLoadError(f"{label} '{path}' must be a .json or .csv file")


def _load_json(path: Path, label: str) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CatalogLoadError(f"{label} '{path}' not found") from exc
    except OSError as exc:
        raise CatalogLoadError(f"could not read {label} '{path}': {exc}") from exc
    try:
        return json.loads(text)
    except JSONDecodeError as exc:
        raise CatalogLoadError(f"{label} '{path}' is not valid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}") from exc


def _coerce_record(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CatalogLoadError(f"{label} must contain objects, got {type(value).__name__}")
    return dict(value)


def _required_string(row: dict[str, Any], field: str, row_label: str) -> str:
    value = row.get(field)
    if value is None or str(value).strip() == "":
        raise CatalogLoadError(f"{row_label}: missing required field '{field}'")
    return str(value).strip()


def _optional_string(row: dict[str, Any], field: str) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _parse_bool(value: Any, label: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"", "false", "0", "no", "n"}:
        return False
    if text in {"true", "1", "yes", "y"}:
        return True
    raise CatalogLoadError(f"{label} must be a boolean-like value")


def _parse_domain_row(row: dict[str, Any], row_label: str) -> Domain | None:
    domain_value = row.get("domain")
    if isinstance(domain_value, dict):
        return _parse_domain_dict(domain_value)
    if isinstance(domain_value, str) and domain_value.strip():
        parsed = _try_parse_json(domain_value, f"{row_label}.domain")
        if isinstance(parsed, dict):
            return _parse_domain_dict(parsed)
        if isinstance(parsed, list):
            return Domain(values=[str(item) for item in parsed])
    min_text = _optional_string(row, "domain_min")
    max_text = _optional_string(row, "domain_max")
    values_text = _optional_string(row, "domain_values")
    if min_text is None and max_text is None and values_text is None:
        return None
    return Domain(
        min=_parse_number(min_text, f"{row_label}.domain_min") if min_text is not None else None,
        max=_parse_number(max_text, f"{row_label}.domain_max") if max_text is not None else None,
        values=_parse_string_list(values_text, f"{row_label}.domain_values") if values_text is not None else None,
    )


def _parse_domain_dict(data: dict[str, Any]) -> Domain:
    values = data.get("values")
    return Domain(
        min=data.get("min"),
        max=data.get("max"),
        values=[str(item) for item in values] if isinstance(values, list) else None,
    )


def _parse_number(value: str, label: str) -> int | float:
    try:
        if any(char in value for char in [".", "e", "E"]):
            return float(value)
        return int(value)
    except ValueError as exc:
        raise CatalogLoadError(f"{label} must be numeric") from exc


def _parse_string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        parsed = _try_parse_json(text, label)
        if not isinstance(parsed, list):
            raise CatalogLoadError(f"{label} JSON must decode to a list")
        return [str(item) for item in parsed]
    parts = [item.strip() for item in text.replace("|", ",").split(",")]
    return [item for item in parts if item]


def _parse_expression(value: Any, label: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        raise CatalogLoadError(f"{label} is required")
    if not isinstance(value, str):
        raise CatalogLoadError(f"{label} must be a JSON object or JSON string")
    parsed = _try_parse_json(value, label)
    if not isinstance(parsed, dict):
        raise CatalogLoadError(f"{label} must decode to a JSON object")
    return parsed


def _parse_phrase_texts(row: dict[str, Any], row_label: str) -> dict[str, str]:
    texts: dict[str, str] = {}
    texts_field = row.get("texts")
    if isinstance(texts_field, dict):
        texts.update({str(key): str(value) for key, value in texts_field.items() if str(value).strip()})
    elif isinstance(texts_field, str) and texts_field.strip():
        parsed = _try_parse_json(texts_field, f"{row_label}.texts")
        if not isinstance(parsed, dict):
            raise CatalogLoadError(f"{row_label}.texts must decode to an object")
        texts.update({str(key): str(value) for key, value in parsed.items() if str(value).strip()})
    for key, value in row.items():
        if not isinstance(key, str) or not key.startswith("text_"):
            continue
        language = key[5:].strip()
        text = str(value).strip()
        if language and text:
            texts[language] = text
    if not texts:
        language = _optional_string(row, "language")
        text = _optional_string(row, "text")
        if language and text:
            texts[language] = text
    if not texts:
        raise CatalogLoadError(f"{row_label}: phrase row must include at least one text_<lang> column or texts object")
    return texts


def _parse_provenance_field(row: dict[str, Any], row_label: str) -> list[ProvenanceRecord]:
    provenance_value = row.get("provenance")
    if isinstance(provenance_value, list):
        return [_parse_provenance_record(item, row_label) for item in provenance_value]
    if isinstance(provenance_value, dict):
        return [_parse_provenance_record(provenance_value, row_label)]
    if isinstance(provenance_value, str) and provenance_value.strip():
        parsed = _try_parse_json(provenance_value, f"{row_label}.provenance")
        if isinstance(parsed, list):
            return [_parse_provenance_record(item, row_label) for item in parsed]
        if isinstance(parsed, dict):
            return [_parse_provenance_record(parsed, row_label)]
        raise CatalogLoadError(f"{row_label}.provenance must decode to an object or list")

    source_id = _optional_string(row, "provenance_source_id")
    if source_id is None:
        raise CatalogLoadError(f"{row_label}: provenance is required")
    return [
        ProvenanceRecord(
            source_id=source_id,
            kind=_optional_string(row, "provenance_kind"),
            location=_optional_string(row, "provenance_location"),
            row=_parse_optional_int(_optional_string(row, "provenance_row"), f"{row_label}.provenance_row"),
            column=_optional_string(row, "provenance_column"),
            table=_optional_string(row, "provenance_table"),
            page=_parse_optional_int(_optional_string(row, "provenance_page"), f"{row_label}.provenance_page"),
            section=_optional_string(row, "provenance_section"),
            note=_optional_string(row, "provenance_note"),
        )
    ]


def _parse_provenance_record(value: Any, row_label: str) -> ProvenanceRecord:
    if not isinstance(value, dict):
        raise CatalogLoadError(f"{row_label}: provenance entries must be objects")
    source_id = value.get("source_id")
    if source_id is None or str(source_id).strip() == "":
        raise CatalogLoadError(f"{row_label}: provenance entry is missing source_id")
    return ProvenanceRecord(
        source_id=str(source_id),
        kind=value.get("kind"),
        location=value.get("location"),
        row=value.get("row"),
        column=value.get("column"),
        table=value.get("table"),
        page=value.get("page"),
        section=value.get("section"),
        note=value.get("note"),
    )


def _domain_to_payload(domain: Domain | None) -> dict[str, Any] | None:
    if domain is None:
        return None
    payload: dict[str, Any] = {}
    if domain.min is not None:
        payload["min"] = domain.min
    if domain.max is not None:
        payload["max"] = domain.max
    if domain.values is not None:
        payload["values"] = domain.values
    return payload or None


def _provenance_to_payload(record: ProvenanceRecord) -> dict[str, Any]:
    return record.to_dict()


def _parse_optional_int(value: str | None, label: str) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise CatalogLoadError(f"{label} must be an integer") from exc


def _try_parse_json(value: str, label: str) -> Any:
    try:
        return json.loads(value)
    except JSONDecodeError as exc:
        raise CatalogLoadError(f"{label} is not valid JSON: {exc.msg}") from exc


def _parse_optional_json_object(value: Any, label: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        parsed = _try_parse_json(text, label)
        if not isinstance(parsed, dict):
            raise CatalogLoadError(f"{label} must decode to a JSON object")
        return parsed
    raise CatalogLoadError(f"{label} must be an object or JSON object string")
