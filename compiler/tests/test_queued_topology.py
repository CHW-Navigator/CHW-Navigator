from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.queued_topology import (
    QueuedTopologyError,
    create_queued_operation,
    parse_topology_snapshot,
    reresolve_queued_operation,
    seal_topology_snapshot,
)
from chw_navigator.diagnostics import DiagnosticCode


EXAMPLE = ROOT / "examples" / "ws6" / "topology-snapshot.json"
LOCK = "sha256:" + "a" * 64


def snapshot_payload() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def snapshot(payload: dict | None = None):
    return parse_topology_snapshot(payload or snapshot_payload())


class QueuedTopologyTests(unittest.TestCase):
    def create(self):
        return create_queued_operation(
            operation_id="report-1::schedule_followup",
            subject_id="synthetic-patient-a",
            assignee_role="chw",
            resolution_lock_digest=LOCK,
            maximum_age_seconds=3600,
            snapshot=snapshot(),
            at="2026-08-06T12:30:00Z",
        )

    def test_fresh_snapshot_resolves_and_carries_every_required_field(self) -> None:
        result = self.create()
        self.assertEqual("resolved", result.status)
        operation = result.operation
        assert operation is not None
        self.assertEqual("synthetic-chw-a", operation.resolved_target_id)
        self.assertEqual(snapshot().content_digest, operation.snapshot_digest)
        self.assertEqual(3600, operation.maximum_age_seconds)
        self.assertEqual(LOCK, operation.resolution_lock_digest)
        self.assertEqual("assignment", operation.boundary_history[0].boundary)

    def test_missing_stale_and_future_snapshots_block_as_stale(self) -> None:
        operation = self.create().operation
        assert operation is not None
        cases = (
            (None, "2026-08-06T12:40:00Z"),
            (snapshot(), "2026-08-06T14:00:01Z"),
            (snapshot(), "2026-08-06T11:59:59Z"),
        )
        for value, at in cases:
            with self.subTest(value=value, at=at):
                result = reresolve_queued_operation(
                    operation,
                    value,
                    boundary="execution",
                    at=at,
                    expected_resolution_lock_digest=LOCK,
                )
                self.assertEqual("blocked_stale_topology", result.status)
                self.assertIsNone(result.operation)
                self.assertEqual(DiagnosticCode.TOPOLOGY_STALE.value, result.diagnostics[0]["code"])

    def test_assignment_change_is_re_resolved_at_every_boundary(self) -> None:
        operation = self.create().operation
        assert operation is not None
        payload = snapshot_payload()
        payload["snapshot_id"] = "synthetic-ws6-2026-08-06-b"
        payload["generated_at"] = "2026-08-06T12:40:00Z"
        payload["assignments"][0]["assignee_id"] = "synthetic-chw-b"
        changed = snapshot(seal_topology_snapshot(payload))
        current = operation
        for boundary, at in (
            ("execution", "2026-08-06T12:41:00Z"),
            ("sync", "2026-08-06T12:42:00Z"),
            ("handoff", "2026-08-06T12:43:00Z"),
        ):
            result = reresolve_queued_operation(
                current,
                changed,
                boundary=boundary,
                at=at,
                expected_resolution_lock_digest=LOCK,
            )
            self.assertEqual("resolved", result.status)
            current = result.operation
            assert current is not None
            self.assertEqual("synthetic-chw-b", current.resolved_target_id)
        self.assertEqual(
            ["assignment", "execution", "sync", "handoff"],
            [item.boundary for item in current.boundary_history],
        )

    def test_duplicate_delivery_and_assignment_order_are_deterministic(self) -> None:
        original = snapshot_payload()
        second_assignment = deepcopy(original["assignments"][0])
        second_assignment.update(
            {
                "assignment_id": "inactive-old",
                "assignee_id": "synthetic-chw-old",
                "active_from": "2026-01-01T00:00:00Z",
                "active_to": "2026-08-01T00:00:00Z",
            }
        )
        original["assignments"].append(second_assignment)
        first = snapshot(seal_topology_snapshot(original))
        permuted = deepcopy(original)
        permuted["assignments"].reverse()
        second = snapshot(seal_topology_snapshot(permuted))
        self.assertEqual(first.content_digest, second.content_digest)
        created = create_queued_operation(
            operation_id="report-1::schedule_followup",
            subject_id="synthetic-patient-a",
            assignee_role="chw",
            resolution_lock_digest=LOCK,
            maximum_age_seconds=3600,
            snapshot=first,
            at="2026-08-06T12:30:00Z",
        ).operation
        assert created is not None
        once = reresolve_queued_operation(
            created,
            second,
            boundary="sync",
            at="2026-08-06T12:31:00Z",
            expected_resolution_lock_digest=LOCK,
        ).operation
        assert once is not None
        duplicate = reresolve_queued_operation(
            once,
            second,
            boundary="sync",
            at="2026-08-06T12:31:00Z",
            expected_resolution_lock_digest=LOCK,
        ).operation
        assert duplicate is not None
        self.assertEqual(once.model_dump(mode="json"), duplicate.model_dump(mode="json"))

    def test_ambiguous_mismatched_and_tampered_inputs_fail_closed(self) -> None:
        payload = snapshot_payload()
        duplicate = deepcopy(payload["assignments"][0])
        duplicate.update({"assignment_id": "second", "assignee_id": "synthetic-chw-b"})
        payload["assignments"].append(duplicate)
        ambiguous = snapshot(seal_topology_snapshot(payload))
        result = create_queued_operation(
            operation_id="report-1::schedule_followup",
            subject_id="synthetic-patient-a",
            assignee_role="chw",
            resolution_lock_digest=LOCK,
            maximum_age_seconds=3600,
            snapshot=ambiguous,
            at="2026-08-06T12:30:00Z",
        )
        self.assertEqual("blocked_topology_resolution", result.status)
        self.assertEqual(
            DiagnosticCode.TOPOLOGY_RESOLUTION_BLOCKED.value,
            result.diagnostics[0]["code"],
        )
        operation = self.create().operation
        assert operation is not None
        with self.assertRaises(QueuedTopologyError) as lock_error:
            reresolve_queued_operation(
                operation,
                snapshot(),
                boundary="execution",
                at="2026-08-06T12:40:00Z",
                expected_resolution_lock_digest="sha256:" + "b" * 64,
            )
        self.assertEqual(DiagnosticCode.QUEUE_CONTRACT_INVALID, lock_error.exception.diagnostics[0].code)
        tampered = snapshot_payload()
        tampered["assignments"][0]["assignee_id"] = "changed-without-digest"
        with self.assertRaises(QueuedTopologyError) as snapshot_error:
            snapshot(tampered)
        self.assertEqual(DiagnosticCode.TOPOLOGY_SNAPSHOT_INVALID, snapshot_error.exception.diagnostics[0].code)


if __name__ == "__main__":
    unittest.main()
