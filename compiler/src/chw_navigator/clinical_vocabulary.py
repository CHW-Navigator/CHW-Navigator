from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from .diagnostics import DiagnosticCode


CLINICAL_VOCABULARY_VERSION = "1.0.0"

CLINICAL_VOCABULARY = {
    "version": CLINICAL_VOCABULARY_VERSION,
    "clinical_terms": (
        "action",
        "classification",
        "classify",
        "clinical-decision",
        "diagnosis",
        "diagnose",
        "diagnostic",
        "disease",
        "drug",
        "fast-breathing",
        "malnutrition",
        "medication",
        "pneumonia",
        "prescription",
        "prescribe",
        "referral",
        "refer",
        "severe-disease",
        "treatment",
        "treat",
    ),
    "derivation_functions": (
        "dx_",
        "deriveDiagnosis",
        "classifyDisease",
        "recommendTreatment",
    ),
    "fhir_clinical_resources": (
        "CarePlan",
        "Condition",
        "MedicationAdministration",
        "MedicationRequest",
        "Observation",
        "Procedure",
        "ServiceRequest",
    ),
}

_TERM_PATTERN = re.compile(
    r"(?:^|[^a-z0-9])(?:action|classification|classify|clinical[ _-]?decision|diagnosis|diagnose|diagnostic|disease|drug|fast[ _-]?breathing|malnutrition|medication|pneumonia|prescription|prescribe|referral|refer|severe[ _-]?(?:disease|pneumonia)|treatment|treat)(?:$|[^a-z0-9])",
    re.IGNORECASE,
)
_DERIVATION_FUNCTION_PATTERN = re.compile(
    r"(?:derive[ _-]?diagnosis|classify[ _-]?disease|recommend[ _-]?treatment|dx_)",
    re.IGNORECASE,
)
_CLINICAL_OPERATOR_PATTERN = re.compile(
    r"(?:\bage\s*(?:<|<=|>|>=)|\bmuac\s*(?:<|<=|>|>=)|\brespiratory(?:_rate|Rate)?\s*(?:<|<=|>|>=)|\brr\s*(?:<|<=|>|>=)|\bspo2\s*(?:<|<=|>|>=))",
    re.IGNORECASE,
)
_CLINICAL_RETURN_PATTERN = re.compile(
    r"return\s*\{[^}]{0,800}(?:action|classification|diagnosis|referral|treatment)\s*:",
    re.IGNORECASE | re.DOTALL,
)
_FHIR_CLINICAL_RESOURCE_PATTERN = re.compile(
    r'''["']resourceType["']\s*:\s*["'](?:CarePlan|Condition|MedicationAdministration|MedicationRequest|Observation|Procedure|ServiceRequest)["']''',
    re.IGNORECASE,
)
_DERIVATION_KEY_PATTERN = re.compile(
    r"^(?:classification|clinicalDecision|diagnosis|diagnosticRule|referralDecision|thresholdExpression|treatmentRecommendation)$",
    re.IGNORECASE,
)


class ClinicalDerivationError(ValueError):
    code = DiagnosticCode.CLINICAL_DERIVATION_FORBIDDEN


def _lexical_form(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return re.sub(r"[._/\\-]+", " ", value).lower()


def contains_clinical_vocabulary(value: str) -> bool:
    return _TERM_PATTERN.search(_lexical_form(value)) is not None


def contains_clinical_derivation(value: str) -> bool:
    lexical = _lexical_form(value)
    return any(
        (
            _DERIVATION_FUNCTION_PATTERN.search(value),
            _FHIR_CLINICAL_RESOURCE_PATTERN.search(value),
            _CLINICAL_RETURN_PATTERN.search(value),
            _TERM_PATTERN.search(lexical) and _CLINICAL_OPERATOR_PATTERN.search(value),
        )
    )


def is_clinical_derivation_key(value: str) -> bool:
    return _DERIVATION_KEY_PATTERN.fullmatch(value) is not None


def clinical_object_findings(value: Any) -> tuple[str, ...]:
    findings: set[str] = set()

    def walk(current: Any, path: str) -> None:
        if isinstance(current, Mapping):
            for key, child in current.items():
                key_text = str(key)
                child_path = key_text if not path else f"{path}.{key_text}"
                if is_clinical_derivation_key(key_text) or (
                    key_text == "resourceType"
                    and isinstance(child, str)
                    and child in CLINICAL_VOCABULARY["fhir_clinical_resources"]
                ):
                    findings.add(child_path)
                walk(child, child_path)
            return
        if isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            for index, child in enumerate(current):
                walk(child, f"{path}[{index}]")
            return
        if isinstance(current, str) and contains_clinical_derivation(current):
            findings.add(path)

    walk(value, "")
    return tuple(sorted(findings))


def reject_clinical_derivation(value: Any, *, context: str) -> None:
    findings = clinical_object_findings(value)
    if findings:
        joined = ", ".join(findings)
        raise ClinicalDerivationError(
            f"{DiagnosticCode.CLINICAL_DERIVATION_FORBIDDEN}: {context} contains clinical-policy derivation at {joined}"
        )
