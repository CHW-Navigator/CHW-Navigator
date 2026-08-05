from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TRACER = ROOT / "contracts" / "examples" / "tracer" / "valid-registry-set.json"
GOVERNANCE = ROOT / "contracts" / "examples" / "governance"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.diagnostics import DiagnosticCode
from chw_navigator.registry_governance import (
    ApprovalAttestation,
    CapabilityGovernanceCatalogue,
    RegistryGovernanceError,
    RegistryRelease,
    RegistrySetV2,
    activate_registry_release,
    parse_attestation,
    parse_registry_release,
    parse_registry_set_v2,
    seal_attestation,
    seal_registry_release,
    seal_registry_set_v2,
)
from chw_navigator.registry_set import RegistrySetError, parse_registry_set, seal_registry_set
from test_data_dictionary import governed_payload


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


def governed_set() -> RegistrySetV2:
    return parse_registry_set_v2(governed_payload())


def attestation(
    registry_digest: str,
    role: str,
    *,
    decision: str = "approved",
    signed_at: str = "2026-08-05T10:00:00Z",
    expires_at: str | None = "2027-01-01T00:00:00Z",
    suffix: str = "",
    approver_id: str | None = None,
) -> ApprovalAttestation:
    return parse_attestation(
        seal_attestation(
            {
                "schema_version": "approval-attestation@1.0.0",
                "content_digest": "sha256:" + "0" * 64,
                "registry_set_digest": registry_digest,
                "role": role,
                "decision": decision,
                "approver_id": approver_id or f"synthetic-test-{role}-approver{suffix}",
                "organization_id": "synthetic-test-moh",
                "signed_at": signed_at,
                "expires_at": expires_at,
                "signing_key_id": f"synthetic-test-{role}-key{suffix}",
                "signature_algorithm": "detached-external",
                "signature": f"synthetic-test-signature-{role}{suffix}",
            }
        )
    )


def three_attestations(registry_digest: str) -> list[ApprovalAttestation]:
    return [attestation(registry_digest, role) for role in ("clinical", "data_governance", "technical")]


def release(registry_digest: str, attestations: list[ApprovalAttestation]) -> RegistryRelease:
    return parse_registry_release(
        seal_registry_release(
            {
                "schema_version": "registry-release@1.0.0",
                "content_digest": "sha256:" + "0" * 64,
                "release_id": "synthetic-test-release",
                "version": "1.0.0",
                "registry_set_digest": registry_digest,
                "attestation_digests": [item.content_digest for item in attestations],
                "effective_from": "2026-08-05T00:00:00Z",
                "expires_at": "2027-01-01T00:00:00Z",
                "supersedes_release_digest": None,
            }
        )
    )


def codes(error: RegistryGovernanceError) -> set[DiagnosticCode]:
    return {item.code for item in error.diagnostics}


class RegistryGovernanceTests(unittest.TestCase):
    def test_three_verified_exact_approvals_activate_only_the_synthetic_fixture(self) -> None:
        registry = governed_set()
        approvals = three_attestations(registry.content_digest)
        activated = activate_registry_release(
            registry,
            release(registry.content_digest, approvals),
            approvals,
            verifier=lambda item: item.signature.startswith("synthetic-test-signature-"),
            at=NOW,
        )
        self.assertEqual(registry.content_digest, activated.registry_set_digest)
        self.assertEqual(3, len(activated.attestation_digests))

    def test_v1_registry_cannot_be_activated(self) -> None:
        registry_v2 = governed_set()
        approvals = three_attestations(registry_v2.content_digest)
        registry_v1 = parse_registry_set(json.loads(TRACER.read_text(encoding="utf-8")))
        with self.assertRaises(RegistryGovernanceError) as raised:
            activate_registry_release(
                registry_v1,
                release(registry_v2.content_digest, approvals),
                approvals,
                verifier=lambda item: True,
                at=NOW,
            )
        self.assertEqual(DiagnosticCode.REGISTRY_RELEASE_REQUIRES_V2, raised.exception.diagnostics[0].code)

    def test_wrong_set_digest_and_governance_binding_fail(self) -> None:
        registry = governed_set()
        wrong = "sha256:" + "f" * 64
        approvals = three_attestations(wrong)
        with self.assertRaises(RegistryGovernanceError) as raised:
            activate_registry_release(
                registry, release(wrong, approvals), approvals, verifier=lambda item: True, at=NOW
            )
        self.assertIn(DiagnosticCode.REGISTRY_APPROVAL_DIGEST_MISMATCH, codes(raised.exception))

        payload = governed_payload()
        payload["capability_governance"]["entries"][0]["capability_content_digest"] = wrong
        payload = seal_registry_set_v2(payload)
        with self.assertRaises(RegistryGovernanceError) as binding:
            parse_registry_set_v2(payload)
        self.assertEqual(DiagnosticCode.REGISTRY_APPROVAL_DIGEST_MISMATCH, binding.exception.diagnostics[0].code)

    def test_concept_binding_is_exact_and_cannot_be_ornamental(self) -> None:
        payload = governed_payload()
        payload["capability_governance"]["entries"][0]["concept_bindings"][0][
            "concept_content_digest"
        ] = "sha256:" + "f" * 64
        payload = seal_registry_set_v2(payload)
        with self.assertRaises(RegistryGovernanceError) as raised:
            parse_registry_set_v2(payload)
        self.assertEqual(DiagnosticCode.REGISTRY_CONCEPT_BINDING_INVALID, raised.exception.diagnostics[0].code)

    def test_activation_rechecks_digests_even_for_preconstructed_models(self) -> None:
        registry = governed_set()
        approvals = three_attestations(registry.content_digest)
        current_release = release(registry.content_digest, approvals)
        tampered = approvals[0].model_copy(update={"content_digest": "sha256:" + "f" * 64})
        supplied = [tampered, approvals[1], approvals[2]]
        with self.assertRaises(RegistryGovernanceError) as raised:
            activate_registry_release(
                registry, current_release, supplied, verifier=lambda item: True, at=NOW
            )
        self.assertEqual(DiagnosticCode.REGISTRY_DIGEST_MISMATCH, raised.exception.diagnostics[0].code)

    def test_missing_and_duplicate_roles_fail_distinctly(self) -> None:
        registry = governed_set()
        missing = three_attestations(registry.content_digest)[:2]
        missing.append(attestation(registry.content_digest, "clinical", suffix="-second"))
        with self.assertRaises(RegistryGovernanceError) as absent:
            activate_registry_release(
                registry, release(registry.content_digest, missing), missing,
                verifier=lambda item: True, at=NOW,
            )
        self.assertIn(DiagnosticCode.REGISTRY_APPROVAL_ROLE_MISSING, codes(absent.exception))

        duplicate = three_attestations(registry.content_digest)
        duplicate.append(attestation(registry.content_digest, "clinical", suffix="-second"))
        with self.assertRaises(RegistryGovernanceError) as repeated:
            activate_registry_release(
                registry, release(registry.content_digest, duplicate), duplicate,
                verifier=lambda item: True, at=NOW,
            )
        self.assertIn(DiagnosticCode.REGISTRY_APPROVAL_ROLE_DUPLICATE, codes(repeated.exception))

        same_person = three_attestations(registry.content_digest)
        same_person[1] = attestation(
            registry.content_digest,
            "data_governance",
            approver_id=same_person[0].approver_id,
        )
        with self.assertRaises(RegistryGovernanceError) as repeated_person:
            activate_registry_release(
                registry, release(registry.content_digest, same_person), same_person,
                verifier=lambda item: True, at=NOW,
            )
        self.assertIn(DiagnosticCode.REGISTRY_APPROVAL_ROLE_DUPLICATE, codes(repeated_person.exception))

    def test_rejected_unverified_and_expired_approvals_fail_distinctly(self) -> None:
        registry = governed_set()
        rejected = three_attestations(registry.content_digest)
        rejected[0] = attestation(registry.content_digest, "clinical", decision="rejected")
        with self.assertRaises(RegistryGovernanceError) as denial:
            activate_registry_release(
                registry, release(registry.content_digest, rejected), rejected,
                verifier=lambda item: True, at=NOW,
            )
        self.assertIn(DiagnosticCode.REGISTRY_APPROVAL_REJECTED, codes(denial.exception))

        approvals = three_attestations(registry.content_digest)
        with self.assertRaises(RegistryGovernanceError) as unverified:
            activate_registry_release(
                registry, release(registry.content_digest, approvals), approvals,
                verifier=lambda item: False, at=NOW,
            )
        self.assertIn(DiagnosticCode.REGISTRY_APPROVAL_UNVERIFIED, codes(unverified.exception))

        expired = three_attestations(registry.content_digest)
        expired[1] = attestation(registry.content_digest, "data_governance", expires_at="2026-08-05T11:00:00Z")
        with self.assertRaises(RegistryGovernanceError) as stale:
            activate_registry_release(
                registry, release(registry.content_digest, expired), expired,
                verifier=lambda item: True, at=NOW,
            )
        self.assertIn(DiagnosticCode.REGISTRY_APPROVAL_EXPIRED, codes(stale.exception))

        future = three_attestations(registry.content_digest)
        future[2] = attestation(registry.content_digest, "technical", signed_at="2026-08-06T10:00:00Z")
        with self.assertRaises(RegistryGovernanceError) as future_dated:
            activate_registry_release(
                registry, release(registry.content_digest, future), future,
                verifier=lambda item: True, at=NOW,
            )
        self.assertIn(DiagnosticCode.REGISTRY_INPUT_INACTIVE, codes(future_dated.exception))

    def test_inactive_or_superseded_inputs_fail(self) -> None:
        payload = governed_payload()
        payload["data_dictionary"]["concepts"][0]["lifecycle_state"] = "reviewed"
        payload = seal_registry_set_v2(payload)
        payload["capability_governance"]["entries"][0]["concept_bindings"][0][
            "concept_content_digest"
        ] = payload["data_dictionary"]["concepts"][0]["content_digest"]
        registry = parse_registry_set_v2(seal_registry_set_v2(payload))
        approvals = three_attestations(registry.content_digest)
        current_release = release(registry.content_digest, approvals)
        with self.assertRaises(RegistryGovernanceError) as inactive:
            activate_registry_release(
                registry, current_release, approvals, verifier=lambda item: True, at=NOW
            )
        self.assertIn(DiagnosticCode.REGISTRY_INPUT_INACTIVE, codes(inactive.exception))

        approved = governed_set()
        approvals = three_attestations(approved.content_digest)
        old_release = release(approved.content_digest, approvals)
        with self.assertRaises(RegistryGovernanceError) as superseded:
            activate_registry_release(
                approved, old_release, approvals, verifier=lambda item: True, at=NOW,
                superseded_release_digests=frozenset({old_release.content_digest}),
            )
        self.assertIn(DiagnosticCode.REGISTRY_INPUT_INACTIVE, codes(superseded.exception))

    def test_candidate_contract_cannot_carry_approval_or_activation(self) -> None:
        payload = json.loads(TRACER.read_text(encoding="utf-8"))
        payload["capability_registry"]["capabilities"][0]["approval"] = {"decision": "approved"}
        payload = seal_registry_set(payload)
        with self.assertRaises(RegistrySetError):
            parse_registry_set(payload)

    def test_schema_runtime_parity_and_negative_fixture_coverage(self) -> None:
        pairs = (
            ("registry-set-v2.schema.json", RegistrySetV2),
            ("capability-governance.schema.json", CapabilityGovernanceCatalogue),
            ("approval-attestation.schema.json", ApprovalAttestation),
            ("registry-release.schema.json", RegistryRelease),
        )
        for name, model in pairs:
            with self.subTest(schema=name):
                schema = json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))
                self.assertFalse(schema["additionalProperties"])
                self.assertEqual(set(model.model_fields), set(schema["required"]))
                self.assertEqual(set(model.model_fields), set(schema["properties"]))
        negative = json.loads((GOVERNANCE / "negative-cases.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {f"CHWN-REG-{index:03d}" for index in range(7, 16)},
            {item["expected_code"] for item in negative["cases"]},
        )


if __name__ == "__main__":
    unittest.main()
