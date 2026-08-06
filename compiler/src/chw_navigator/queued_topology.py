from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .diagnostics import Diagnostic, DiagnosticCode


Digest = str
QueueBoundary = Literal["assignment", "execution", "sync", "handoff"]
TOPOLOGY_SNAPSHOT_SCHEMA_VERSION = "topology-snapshot@1.0.0"
QUEUED_OPERATION_SCHEMA_VERSION = "queued-operation@1.0.0"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TopologyAssignment(_StrictModel):
    assignment_id: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    assignee_role: str = Field(min_length=1)
    assignee_id: str = Field(min_length=1)
    active_from: datetime
    active_to: datetime | None

    @field_validator("active_from", "active_to")
    @classmethod
    def aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("topology timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def interval_is_ordered(self) -> "TopologyAssignment":
        if self.active_to is not None and self.active_to <= self.active_from:
            raise ValueError("assignment active_to must be later than active_from")
        return self


class TopologySnapshot(_StrictModel):
    schema_version: Literal[TOPOLOGY_SNAPSHOT_SCHEMA_VERSION]
    content_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    snapshot_id: str = Field(min_length=1)
    generated_at: datetime
    assignments: tuple[TopologyAssignment, ...]

    @field_validator("generated_at")
    @classmethod
    def generated_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("topology timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def assignment_ids_are_unique(self) -> "TopologySnapshot":
        values = [item.assignment_id for item in self.assignments]
        if len(values) != len(set(values)):
            raise ValueError("duplicate topology assignment ids are forbidden")
        return self


class QueueBoundaryRecord(_StrictModel):
    boundary: QueueBoundary
    checked_at: datetime
    snapshot_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    resolved_target_id: str = Field(min_length=1)

    @field_validator("checked_at")
    @classmethod
    def checked_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("queue timestamps must include a timezone")
        return value


class QueuedOperation(_StrictModel):
    schema_version: Literal[QUEUED_OPERATION_SCHEMA_VERSION]
    content_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    operation_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
    subject_id: str = Field(min_length=1)
    assignee_role: str = Field(min_length=1)
    resolved_target_id: str = Field(min_length=1)
    snapshot_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    resolved_at: datetime
    maximum_age_seconds: int = Field(gt=0)
    resolution_lock_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    boundary_history: tuple[QueueBoundaryRecord, ...] = Field(min_length=1)

    @field_validator("resolved_at")
    @classmethod
    def resolved_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("queue timestamps must include a timezone")
        return value


class QueueResolutionResult(_StrictModel):
    status: Literal["resolved", "blocked_stale_topology", "blocked_topology_resolution"]
    operation: QueuedOperation | None
    diagnostics: tuple[dict[str, Any], ...]


class QueuedTopologyError(ValueError):
    def __init__(self, diagnostics: list[Diagnostic] | tuple[Diagnostic, ...]):
        self.diagnostics = tuple(diagnostics)
        super().__init__(
            "Queued topology validation failed closed:\n"
            + "\n".join(f"{item.code}: {item.message}" for item in self.diagnostics)
        )


def _diagnostic(code: DiagnosticCode, message: str, path: str | None = None) -> Diagnostic:
    return Diagnostic(code=code, severity="error", message=message, path=path)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: item.isoformat() if isinstance(item, datetime) else str(item),
    ).encode("utf-8")


def _digest(payload: dict[str, Any]) -> str:
    value = copy.deepcopy(payload)
    value.pop("content_digest", None)
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _iso(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise QueuedTopologyError(
            [_diagnostic(DiagnosticCode.QUEUE_CONTRACT_INVALID, "Evaluation time must include a timezone.")]
        )
    return parsed.astimezone(timezone.utc)


def seal_topology_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(payload)
    sealed["assignments"] = sorted(
        sealed.get("assignments", []),
        key=lambda item: (
            item.get("subject_id", ""),
            item.get("assignee_role", ""),
            item.get("active_from", ""),
            item.get("assignment_id", ""),
        ),
    )
    sealed["content_digest"] = "sha256:" + "0" * 64
    normalized = TopologySnapshot.model_validate(sealed).model_dump(mode="json")
    normalized["content_digest"] = _digest(normalized)
    return normalized


def seal_queued_operation(payload: dict[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(payload)
    sealed["content_digest"] = "sha256:" + "0" * 64
    normalized = QueuedOperation.model_validate(sealed).model_dump(mode="json")
    normalized["content_digest"] = _digest(normalized)
    return normalized


def _parse(model: type[_StrictModel], payload: Any, code: DiagnosticCode) -> _StrictModel:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise QueuedTopologyError(
            [
                _diagnostic(
                    code,
                    str(item["msg"]),
                    "$" + "".join(
                        f"[{part}]" if isinstance(part, int) else f".{part}" for part in item["loc"]
                    ),
                )
                for item in exc.errors(include_url=False)
            ]
        ) from exc


def parse_topology_snapshot(payload: Any) -> TopologySnapshot:
    document = _parse(TopologySnapshot, payload, DiagnosticCode.TOPOLOGY_SNAPSHOT_INVALID)
    assert isinstance(document, TopologySnapshot)
    expected = seal_topology_snapshot(document.model_dump(mode="json"))["content_digest"]
    if document.content_digest != expected:
        raise QueuedTopologyError(
            [_diagnostic(DiagnosticCode.TOPOLOGY_SNAPSHOT_INVALID, "Topology snapshot digest does not match.", "$.content_digest")]
        )
    return document


def parse_queued_operation(payload: Any) -> QueuedOperation:
    document = _parse(QueuedOperation, payload, DiagnosticCode.QUEUE_CONTRACT_INVALID)
    assert isinstance(document, QueuedOperation)
    if document.content_digest != _digest(document.model_dump(mode="json")):
        raise QueuedTopologyError(
            [_diagnostic(DiagnosticCode.QUEUE_CONTRACT_INVALID, "Queued operation digest does not match.", "$.content_digest")]
        )
    return document


def _active_targets(
    snapshot: TopologySnapshot,
    *,
    subject_id: str,
    assignee_role: str,
    at: datetime,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                item.assignee_id
                for item in snapshot.assignments
                if item.subject_id == subject_id
                and item.assignee_role == assignee_role
                and item.active_from <= at
                and (item.active_to is None or at < item.active_to)
            }
        )
    )


def _blocked(
    status: Literal["blocked_stale_topology", "blocked_topology_resolution"],
    diagnostic: Diagnostic,
) -> QueueResolutionResult:
    return QueueResolutionResult(
        status=status,
        operation=None,
        diagnostics=(
            {
                "code": diagnostic.code.value,
                "severity": diagnostic.severity,
                "message": diagnostic.message,
                **({"path": diagnostic.path} if diagnostic.path else {}),
            },
        ),
    )


def _fresh_snapshot(
    snapshot: TopologySnapshot | None,
    *,
    at: datetime,
    maximum_age_seconds: int,
) -> QueueResolutionResult | None:
    if snapshot is None:
        return _blocked(
            "blocked_stale_topology",
            _diagnostic(DiagnosticCode.TOPOLOGY_STALE, "No topology snapshot is available."),
        )
    age = (at - snapshot.generated_at.astimezone(timezone.utc)).total_seconds()
    if age < 0:
        return _blocked(
            "blocked_stale_topology",
            _diagnostic(DiagnosticCode.TOPOLOGY_STALE, "The topology snapshot is future-dated.", "$.generated_at"),
        )
    if age > maximum_age_seconds:
        return _blocked(
            "blocked_stale_topology",
            _diagnostic(DiagnosticCode.TOPOLOGY_STALE, "The topology snapshot is older than the permitted maximum age.", "$.generated_at"),
        )
    return None


def create_queued_operation(
    *,
    operation_id: str,
    subject_id: str,
    assignee_role: str,
    resolution_lock_digest: str,
    maximum_age_seconds: int,
    snapshot: TopologySnapshot,
    at: datetime | str,
) -> QueueResolutionResult:
    checked_at = _iso(at)
    snapshot = parse_topology_snapshot(snapshot.model_dump(mode="json"))
    stale = _fresh_snapshot(snapshot, at=checked_at, maximum_age_seconds=maximum_age_seconds)
    if stale is not None:
        return stale
    targets = _active_targets(
        snapshot, subject_id=subject_id, assignee_role=assignee_role, at=checked_at
    )
    if len(targets) != 1:
        return _blocked(
            "blocked_topology_resolution",
            _diagnostic(
                DiagnosticCode.TOPOLOGY_RESOLUTION_BLOCKED,
                f"Expected one active assignment; found {len(targets)}.",
                "$.assignments",
            ),
        )
    payload = seal_queued_operation(
        {
            "schema_version": QUEUED_OPERATION_SCHEMA_VERSION,
            "content_digest": "sha256:" + "0" * 64,
            "operation_id": operation_id,
            "subject_id": subject_id,
            "assignee_role": assignee_role,
            "resolved_target_id": targets[0],
            "snapshot_digest": snapshot.content_digest,
            "resolved_at": checked_at.isoformat(),
            "maximum_age_seconds": maximum_age_seconds,
            "resolution_lock_digest": resolution_lock_digest,
            "boundary_history": [
                {
                    "boundary": "assignment",
                    "checked_at": checked_at.isoformat(),
                    "snapshot_digest": snapshot.content_digest,
                    "resolved_target_id": targets[0],
                }
            ],
        }
    )
    operation = parse_queued_operation(payload)
    return QueueResolutionResult(status="resolved", operation=operation, diagnostics=())


def reresolve_queued_operation(
    operation: QueuedOperation,
    snapshot: TopologySnapshot | None,
    *,
    boundary: QueueBoundary,
    at: datetime | str,
    expected_resolution_lock_digest: str,
) -> QueueResolutionResult:
    operation = parse_queued_operation(operation.model_dump(mode="json"))
    checked_at = _iso(at)
    if operation.resolution_lock_digest != expected_resolution_lock_digest:
        raise QueuedTopologyError(
            [_diagnostic(DiagnosticCode.QUEUE_CONTRACT_INVALID, "Queued operation uses a different resolution lock.", "$.resolution_lock_digest")]
        )
    parsed_snapshot = (
        parse_topology_snapshot(snapshot.model_dump(mode="json")) if snapshot is not None else None
    )
    stale = _fresh_snapshot(
        parsed_snapshot,
        at=checked_at,
        maximum_age_seconds=operation.maximum_age_seconds,
    )
    if stale is not None:
        return stale
    assert parsed_snapshot is not None
    targets = _active_targets(
        parsed_snapshot,
        subject_id=operation.subject_id,
        assignee_role=operation.assignee_role,
        at=checked_at,
    )
    if len(targets) != 1:
        return _blocked(
            "blocked_topology_resolution",
            _diagnostic(
                DiagnosticCode.TOPOLOGY_RESOLUTION_BLOCKED,
                f"Expected one active assignment; found {len(targets)}.",
                "$.assignments",
            ),
        )
    record = {
        "boundary": boundary,
        "checked_at": checked_at.isoformat(),
        "snapshot_digest": parsed_snapshot.content_digest,
        "resolved_target_id": targets[0],
    }
    record = QueueBoundaryRecord.model_validate(record).model_dump(mode="json")
    history = [item.model_dump(mode="json") for item in operation.boundary_history]
    if history and history[-1] == record:
        return QueueResolutionResult(status="resolved", operation=operation, diagnostics=())
    payload = operation.model_dump(mode="json")
    payload.update(
        {
            "resolved_target_id": targets[0],
            "snapshot_digest": parsed_snapshot.content_digest,
            "resolved_at": checked_at.isoformat(),
            "boundary_history": [*history, record],
        }
    )
    updated = parse_queued_operation(seal_queued_operation(payload))
    return QueueResolutionResult(status="resolved", operation=updated, diagnostics=())
