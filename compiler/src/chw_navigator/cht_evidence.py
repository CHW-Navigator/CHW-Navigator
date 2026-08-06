from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from .diagnostics import Diagnostic, DiagnosticCode


SUPPORTED_CHT_PROFILES = ("4.22.0", "5.2.0")
EvidenceStatus = Literal["pass", "fail", "skipped", "not_run"]


@dataclass(frozen=True, slots=True)
class CHTEvidenceRecord:
    check: str
    profile: str
    status: EvidenceStatus
    evidence_level: str
    executed: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class CHTEvidenceError(ValueError):
    def __init__(self, diagnostic: Diagnostic):
        self.diagnostics = (diagnostic,)
        super().__init__(f"{diagnostic.code}: {diagnostic.message}")


def _error(message: str) -> CHTEvidenceError:
    return CHTEvidenceError(
        Diagnostic(
            code=DiagnosticCode.EVIDENCE_RUNNER_INVALID,
            severity="error",
            message=message,
            path="evidence",
        )
    )


def official_harness_record(
    profile: str,
    *,
    executed: bool,
    passed: bool | None = None,
    reason: str,
) -> CHTEvidenceRecord:
    if profile not in SUPPORTED_CHT_PROFILES:
        raise _error(f"Unsupported CHT evidence profile '{profile}'.")
    if not executed:
        if passed is not None:
            raise _error("An unexecuted official harness cannot have a pass/fail result.")
        return CHTEvidenceRecord(
            check="official_local_harness",
            profile=profile,
            status="not_run",
            evidence_level="E3",
            executed=False,
            reason=reason,
        )
    if passed is None:
        raise _error("An executed official harness must report pass or fail.")
    return CHTEvidenceRecord(
        check="official_local_harness",
        profile=profile,
        status="pass" if passed else "fail",
        evidence_level="E3",
        executed=True,
        reason=reason,
    )


def exact_target_record(
    profile: str,
    *,
    executed: bool,
    passed: bool | None = None,
    reason: str,
) -> CHTEvidenceRecord:
    if profile not in SUPPORTED_CHT_PROFILES:
        raise _error(f"Unsupported CHT evidence profile '{profile}'.")
    if not executed:
        if passed is not None:
            raise _error("An unexecuted exact-target check cannot have a pass/fail result.")
        return CHTEvidenceRecord(
            check="exact_target_runtime",
            profile=profile,
            status="not_run",
            evidence_level="E4",
            executed=False,
            reason=reason,
        )
    if passed is None:
        raise _error("An executed exact-target check must report pass or fail.")
    return CHTEvidenceRecord(
        check="exact_target_runtime",
        profile=profile,
        status="pass" if passed else "fail",
        evidence_level="E4",
        executed=True,
        reason=reason,
    )


def default_runner_records() -> tuple[CHTEvidenceRecord, ...]:
    records: list[CHTEvidenceRecord] = []
    for profile in SUPPORTED_CHT_PROFILES:
        records.append(
            official_harness_record(
                profile,
                executed=False,
                reason="Official browser/form harness was not invoked for this build.",
            )
        )
        records.append(
            exact_target_record(
                profile,
                executed=False,
                reason="Exact CHT sandbox, server, and device runtime are external evidence.",
            )
        )
    return tuple(records)
