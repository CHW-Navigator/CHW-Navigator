from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import json
from pathlib import Path
from typing import Any

from .diagnostics import Diagnostic, DiagnosticCode


SPECIAL_FUNCTION_STATUSES = (
    "ok",
    "input_missing",
    "input_invalid",
    "outside_supported_domain",
    "reference_data_unavailable",
    "numeric_failure",
    "version_mismatch",
    "execution_failure",
)

GESTATIONAL_AGE_FUNCTION_ID = "special.technical.gestational-age-and-edd-from-lmp"
GESTATIONAL_AGE_FUNCTION_VERSION = "1.0.0"
GESTATIONAL_AGE_REFERENCE_VERSION = "calendar-280-day-v1"
GESTATIONAL_AGE_REFERENCE_SHA256 = "sha256:24a7f281b2356f585f883d459f49b8f74b7059308039b96cedac2b7d1b9123eb"


@dataclass(frozen=True, slots=True)
class SpecialFunctionResult:
    status: str
    technical: dict[str, Any] | None = None
    provenance: dict[str, str] | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


def _parse_iso_date(value: str) -> date | None:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.isoformat() == value else None


def calculate_gestational_age_from_lmp(
    *,
    lmp_date: str | None,
    as_of_date: str | None,
    function_version: str | None = GESTATIONAL_AGE_FUNCTION_VERSION,
    reference_data_version: str | None = GESTATIONAL_AGE_REFERENCE_VERSION,
    reference_available: bool = True,
) -> SpecialFunctionResult:
    if not reference_available:
        return SpecialFunctionResult(
            status="reference_data_unavailable",
            reason="The pinned calendar convention is unavailable.",
        )
    if None in (lmp_date, as_of_date, function_version, reference_data_version):
        return SpecialFunctionResult(
            status="input_missing",
            reason="lmp_date, as_of_date, function_version, and reference_data_version are required.",
        )
    if (
        function_version != GESTATIONAL_AGE_FUNCTION_VERSION
        or reference_data_version != GESTATIONAL_AGE_REFERENCE_VERSION
    ):
        return SpecialFunctionResult(
            status="version_mismatch",
            reason="Function or reference-data version does not match the registered implementation.",
        )
    lmp = _parse_iso_date(lmp_date)
    as_of = _parse_iso_date(as_of_date)
    if lmp is None or as_of is None:
        return SpecialFunctionResult(status="input_invalid", reason="Dates must be real ISO 8601 calendar dates.")
    elapsed_days = (as_of - lmp).days
    if elapsed_days < 0 or elapsed_days > 315:
        return SpecialFunctionResult(
            status="outside_supported_domain",
            reason="LMP must not be in the future or more than 315 days before as_of_date.",
        )
    try:
        weeks = (Decimal(elapsed_days) / Decimal(7)).quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)
        estimated_delivery_date = (lmp + timedelta(days=280)).isoformat()
    except (ArithmeticError, OverflowError, ValueError):
        return SpecialFunctionResult(status="numeric_failure", reason="Calendar arithmetic failed.")
    numeric_weeks: int | float = int(weeks) if weeks == weeks.to_integral() else float(weeks)
    return SpecialFunctionResult(
        status="ok",
        technical={
            "gestational_age_weeks": numeric_weeks,
            "estimated_delivery_date": estimated_delivery_date,
        },
        provenance={
            "function_id": GESTATIONAL_AGE_FUNCTION_ID,
            "function_version": GESTATIONAL_AGE_FUNCTION_VERSION,
            "reference_data_version": GESTATIONAL_AGE_REFERENCE_VERSION,
            "reference_data_sha256": GESTATIONAL_AGE_REFERENCE_SHA256,
            "rounding": "half-even-1",
        },
    )


def validate_extension_return(value: Any) -> list[Diagnostic]:
    valid = isinstance(value, dict) and value.get("t") == "str" and isinstance(value.get("v"), str)
    if valid:
        status = value["v"].split("|", 1)[0]
        valid = status in SPECIAL_FUNCTION_STATUSES
    return [] if valid else [
        Diagnostic(
            DiagnosticCode.INVALID_EXTENSION_RETURN,
            "error",
            "CHT extension results must be a string envelope containing a registered status and payload.",
        )
    ]


def validate_status_coverage(text: str) -> list[Diagnostic]:
    missing = [status for status in SPECIAL_FUNCTION_STATUSES if status not in text]
    return [] if not missing else [
        Diagnostic(
            DiagnosticCode.STATUS_COVERAGE_INCOMPLETE,
            "error",
            f"Special-function lowering is missing status branches: {', '.join(missing)}.",
        )
    ]


def sha256_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def sha256_file(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def verify_registry_digests(
    registry_path: Path,
    *,
    implementation_source: str,
    vector_path: Path,
) -> list[Diagnostic]:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    function = registry["functions"][GESTATIONAL_AGE_FUNCTION_ID]
    diagnostics: list[Diagnostic] = []
    if function["implementation_digest"] != sha256_text(implementation_source):
        diagnostics.append(
            Diagnostic(
                DiagnosticCode.IMPLEMENTATION_DIGEST_MISMATCH,
                "error",
                "Registered implementation digest does not match the generated extension module.",
            )
        )
    if function["golden_vector_digest"] != sha256_file(vector_path):
        diagnostics.append(
            Diagnostic(
                DiagnosticCode.VECTOR_DIGEST_MISMATCH,
                "error",
                "Registered golden-vector digest does not match the vector file.",
            )
        )
    return diagnostics
