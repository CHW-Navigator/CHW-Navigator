from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
EXAMPLES = ROOT / "examples" / "ws5"
TRACER = ROOT / "examples" / "tracer"
GOVERNED = ROOT / "contracts" / "examples" / "governance" / "valid-registry-set-v2.json"

from chw_navigator.canonical_bridge import (
    CanonicalBridgeError,
    ProductCanonicalAdapter,
    ReviewedCapabilityNeeds,
    adapt_product_logic,
    apply_resolution_to_ir,
    build_ws5_package,
    parse_product_adapter,
    parse_reviewed_needs,
    resolve_reviewed_needs,
    seal_reviewed_needs,
    write_ws5_package,
)
from chw_navigator.cht_local_data import load_cht_local_data_registry
from chw_navigator.cli import main
from chw_navigator.diagnostics import DiagnosticCode
from chw_navigator.registry_governance import (
    ActivatedRegistryRelease,
    parse_registry_set_v2,
    seal_registry_set_v2,
)
from chw_navigator.registry_set import TargetProfile, content_digest
from chw_navigator.tracer import build_tracer


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def source_candidate() -> dict:
    return load(EXAMPLES / "candidate-capability-needs.json")


def inputs():
    product = load(EXAMPLES / "product-clinical-logic.json")
    adapter = parse_product_adapter(load(EXAMPLES / "product-canonical-adapter.json"))
    local = load_cht_local_data_registry(TRACER / "local-data-bindings.json")
    reviewed = parse_reviewed_needs(load(EXAMPLES / "reviewed-capability-needs.json"))
    registry = parse_registry_set_v2(load(GOVERNED))
    activated = ActivatedRegistryRelease.model_validate(load(EXAMPLES / "synthetic-activated-release.json"))
    target = TargetProfile.model_validate(load(EXAMPLES / "target-profile.json"))
    return product, adapter, local, reviewed, registry, activated, target


def mutate_reviewed(reviewed: ReviewedCapabilityNeeds, mutate) -> ReviewedCapabilityNeeds:
    payload = reviewed.model_dump(mode="json")
    mutate(payload)
    return parse_reviewed_needs(seal_reviewed_needs(payload))


def codes(error: CanonicalBridgeError) -> set[DiagnosticCode]:
    return {item.code for item in error.diagnostics}


class ProductAdapterTests(unittest.TestCase):
    def test_all_seven_sections_and_supported_variable_fields_are_accounted_for(self):
        product, adapter, local, *_ = inputs()
        result = adapt_product_logic(product, adapter, local)
        self.assertIsNotNone(result.canonical_ir)
        self.assertEqual(result.loss_report["status"], "complete")
        self.assertEqual(
            [item["section"] for item in result.loss_report["sections"]],
            ["supply_list", "variables", "predicates", "modules", "router", "integrative", "phrase_bank"],
        )
        variable_section = next(
            item for item in result.loss_report["sections"] if item["section"] == "variables"
        )
        mapped = {item["source_path"] for item in variable_section["mappings"]}
        for index, variable in enumerate(product["variables"]):
            for field in variable:
                self.assertIn(f"$.variables[{index}].{field}", mapped)
        self.assertEqual(
            result.canonical_ir["variables"]["st_lmp_date_h"]["history_binding"]["record_key"],
            "local.person.lmp_date@1.0.0",
        )

    def test_unknown_field_blocks_and_survives_in_loss_report(self):
        product, adapter, local, *_ = inputs()
        product["variables"][0]["invented"] = "must not disappear"
        result = adapt_product_logic(product, adapter, local)
        self.assertIsNone(result.canonical_ir)
        self.assertEqual(result.loss_report["status"], "blocked")
        self.assertIn(
            DiagnosticCode.PRODUCT_FIELD_UNSUPPORTED.value,
            {item["code"] for item in result.loss_report["diagnostics"]},
        )
        variable_section = next(
            item for item in result.loss_report["sections"] if item["section"] == "variables"
        )
        self.assertEqual(variable_section["source_digest"], result.loss_report["sections"][1]["source_digest"])

    def test_nonempty_unsupported_clinical_section_stops_instead_of_inferring(self):
        product, adapter, local, *_ = inputs()
        product["modules"] = [{"module_id": "mod_unparsed", "clinical_rule": "guess me"}]
        result = adapt_product_logic(product, adapter, local)
        self.assertIsNone(result.canonical_ir)
        diagnostic = next(item for item in result.loss_report["diagnostics"] if item["path"] == "$.modules")
        self.assertEqual(diagnostic["code"], DiagnosticCode.PRODUCT_FIELD_UNSUPPORTED.value)

    def test_missing_provenance_fails_with_stable_diagnostic(self):
        product, adapter, local, *_ = inputs()
        product["variables"][0]["source_quote"] = ""
        result = adapt_product_logic(product, adapter, local)
        self.assertIsNone(result.canonical_ir)
        self.assertIn(
            DiagnosticCode.PRODUCT_PROVENANCE_LOSS.value,
            {item["code"] for item in result.loss_report["diagnostics"]},
        )

    def test_coercible_product_values_are_rejected_not_defaulted(self):
        product, adapter, local, *_ = inputs()
        product["variables"][0]["allowed_missingness"] = "true"
        result = adapt_product_logic(product, adapter, local)
        self.assertIsNone(result.canonical_ir)
        self.assertIn(
            DiagnosticCode.PRODUCT_CONTRACT_INVALID.value,
            {item["code"] for item in result.loss_report["diagnostics"]},
        )

    def test_unregistered_local_data_binding_fails_closed(self):
        product, adapter, local, *_ = inputs()
        payload = adapter.model_dump(mode="json")
        payload["local_data_reads"][0]["binding_id"] = "local.person.unknown@1.0.0"
        from chw_navigator.canonical_bridge import seal_product_adapter

        adapter = parse_product_adapter(seal_product_adapter(payload))
        result = adapt_product_logic(product, adapter, local)
        self.assertIsNone(result.canonical_ir)
        self.assertIn("CHT-LOCAL-002", {item["code"] for item in result.loss_report["diagnostics"]})


class ExactResolutionTests(unittest.TestCase):
    def test_exact_resolution_emits_lock_without_implementation_names(self):
        product, adapter, local, reviewed, registry, activated, target = inputs()
        package = build_ws5_package(
            product, source_candidate(), adapter, local, reviewed, registry, activated, target
        )
        resolution = package.resolution_lock["resolutions"][0]
        self.assertEqual(resolution["capability_id"], "technical.gestational-age.naegele")
        self.assertEqual(resolution["resolution_rule_version"], "exact-semantic-resolution@1.0.0")
        rendered_ir = json.dumps(package.canonical_ir, sort_keys=True)
        self.assertNotIn("python_module", rendered_ir)
        self.assertNotIn("calculate_gestational_age_naegele", rendered_ir)
        self.assertNotIn("gestational-age-from-lmp.js", rendered_ir)
        action = package.canonical_ir["actions"]["a_gestational_age_naegele"]
        self.assertEqual(list(action["arguments"]), ["lmp_date", "reference_date"])
        self.assertTrue(all(value.startswith("st_") for value in action["outputs"]))
        self.assertIn("o_gestational_age_naegele_usable", package.canonical_ir["outputs"])

    def test_registry_order_and_candidate_origin_do_not_change_outputs(self):
        product, adapter, local, reviewed, registry, activated, target = inputs()
        first = build_ws5_package(
            product, source_candidate(), adapter, local, reviewed, registry, activated, target
        )
        extra_payload = registry.model_dump(mode="json")
        extra = deepcopy(extra_payload["capability_registry"]["capabilities"][0])
        extra["id"] = "technical.unrelated"
        extra["operation"] = "unrelated_operation"
        extra["content_digest"] = "sha256:" + "0" * 64
        extra_payload["capability_registry"]["capabilities"].append(extra)
        extra_payload = seal_registry_set_v2(extra_payload)
        governance = deepcopy(extra_payload["capability_governance"]["entries"][0])
        governance["capability_id"] = extra["id"]
        governance["capability_content_digest"] = extra_payload["capability_registry"]["capabilities"][1]["content_digest"]
        governance["content_digest"] = "sha256:" + "0" * 64
        extra_payload["capability_governance"]["entries"].append(governance)
        ordered = parse_registry_set_v2(seal_registry_set_v2(extra_payload))
        ordered_activation = activated.model_copy(update={"registry_set_digest": ordered.content_digest})
        ordered_first = build_ws5_package(
            product, source_candidate(), adapter, local, reviewed, ordered,
            ordered_activation, ordered.target_profile
        )
        reversed_payload = ordered.model_dump(mode="json")
        reversed_payload["capability_registry"]["capabilities"].reverse()
        reversed_payload["capability_governance"]["entries"].reverse()
        reordered = parse_registry_set_v2(seal_registry_set_v2(reversed_payload))
        reordered_activation = activated.model_copy(
            update={"registry_set_digest": reordered.content_digest}
        )
        second = build_ws5_package(
            product, source_candidate(), adapter, local, reviewed, reordered,
            reordered_activation, reordered.target_profile
        )
        self.assertEqual(ordered_first.canonical_ir, second.canonical_ir)
        for field in (
            "need_id", "capability_id", "capability_version",
            "capability_content_digest", "resolution_rule_version", "rationale",
        ):
            self.assertEqual(
                ordered_first.resolution_lock["resolutions"][0][field],
                second.resolution_lock["resolutions"][0][field],
            )
        self.assertEqual(first.canonical_ir, second.canonical_ir)

        human = mutate_reviewed(reviewed, lambda payload: payload.update({"authoring_origin": "human"}))
        third = build_ws5_package(
            product, source_candidate(), adapter, local, human, registry, activated, target
        )
        self.assertEqual(first.canonical_ir, third.canonical_ir)
        self.assertEqual(first.resolution_lock, third.resolution_lock)

    def test_zero_match_and_contract_mismatch_are_distinct(self):
        *_, reviewed, registry, activated, target = inputs()
        absent = mutate_reviewed(
            reviewed,
            lambda payload: payload["needs"][0].update({"operation": "not_registered"}),
        )
        with self.assertRaises(CanonicalBridgeError) as unresolved:
            resolve_reviewed_needs(absent, registry, activated, target)
        self.assertEqual(codes(unresolved.exception), {DiagnosticCode.CAPABILITY_NEED_UNRESOLVED})

        wrong_unit = mutate_reviewed(
            reviewed,
            lambda payload: payload["needs"][0]["inputs"][0].update({"unit": "weeks"}),
        )
        with self.assertRaises(CanonicalBridgeError) as mismatch:
            resolve_reviewed_needs(wrong_unit, registry, activated, target)
        self.assertEqual(codes(mismatch.exception), {DiagnosticCode.CAPABILITY_NEED_CONTRACT_MISMATCH})

        wrong_order = mutate_reviewed(
            reviewed,
            lambda payload: payload["needs"][0]["inputs"].reverse(),
        )
        with self.assertRaises(CanonicalBridgeError) as ordered:
            resolve_reviewed_needs(wrong_order, registry, activated, target)
        self.assertEqual(codes(ordered.exception), {DiagnosticCode.CAPABILITY_NEED_CONTRACT_MISMATCH})

    def test_reviewed_contract_rejects_implementation_fields_and_bad_digest(self):
        payload = load(EXAMPLES / "reviewed-capability-needs.json")
        payload["needs"][0]["python_symbol"] = "calculate_gestational_age_naegele"
        with self.assertRaises(CanonicalBridgeError) as extra:
            parse_reviewed_needs(payload)
        self.assertEqual(codes(extra.exception), {DiagnosticCode.PRODUCT_CONTRACT_INVALID})

        payload = load(EXAMPLES / "reviewed-capability-needs.json")
        payload["needs"][0]["operation"] = "changed_without_resealing"
        with self.assertRaises(CanonicalBridgeError) as digest:
            parse_reviewed_needs(payload)
        self.assertEqual(codes(digest.exception), {DiagnosticCode.PRODUCT_CONTRACT_INVALID})

        *_, reviewed, registry, activated, target = inputs()
        tampered = reviewed.model_copy(update={"content_digest": "sha256:" + "f" * 64})
        with self.assertRaises(CanonicalBridgeError) as direct_model:
            resolve_reviewed_needs(tampered, registry, activated, target)
        self.assertEqual(
            codes(direct_model.exception),
            {DiagnosticCode.PRODUCT_CONTRACT_INVALID},
        )

    def test_source_wording_never_selects_or_changes_a_capability(self):
        *_, reviewed, registry, activated, target = inputs()
        original = resolve_reviewed_needs(reviewed, registry, activated, target)
        rewritten = mutate_reviewed(
            reviewed,
            lambda payload: payload["needs"][0]["source"].update({
                "quote": (
                    "Completely different reviewed wording, even mentioning "
                    "technical.gestational-age.naegele, is not a selector."
                )
            }),
        )
        changed = resolve_reviewed_needs(rewritten, registry, activated, target)
        self.assertEqual(original, changed)

        misleading = mutate_reviewed(
            rewritten,
            lambda payload: payload["needs"][0].update({"operation": "not_registered"}),
        )
        with self.assertRaises(CanonicalBridgeError) as unresolved:
            resolve_reviewed_needs(misleading, registry, activated, target)
        self.assertEqual(
            codes(unresolved.exception),
            {DiagnosticCode.CAPABILITY_NEED_UNRESOLVED},
        )

    def test_review_is_bound_to_the_exact_registry_blind_candidate(self):
        product, adapter, local, reviewed, registry, activated, target = inputs()
        changed_candidate = source_candidate()
        changed_candidate["candidates"][0]["problem"] += " Changed after review."
        with self.assertRaises(CanonicalBridgeError) as raised:
            build_ws5_package(
                product,
                changed_candidate,
                adapter,
                local,
                reviewed,
                registry,
                activated,
                target,
            )
        self.assertEqual(
            codes(raised.exception),
            {DiagnosticCode.PRODUCT_CONTRACT_INVALID},
        )

    def test_preconstructed_adapter_and_resolution_lock_are_reverified(self):
        product, adapter, local, reviewed, registry, activated, target = inputs()
        tampered_adapter = adapter.model_copy(update={"source_id": "changed-after-parse"})
        with self.assertRaises(CanonicalBridgeError) as adapter_error:
            build_ws5_package(
                product,
                source_candidate(),
                tampered_adapter,
                local,
                reviewed,
                registry,
                activated,
                target,
            )
        self.assertEqual(
            codes(adapter_error.exception),
            {DiagnosticCode.PRODUCT_CONTRACT_INVALID},
        )

        bridge = adapt_product_logic(product, adapter, local)
        self.assertIsNotNone(bridge.canonical_ir)
        lock = resolve_reviewed_needs(reviewed, registry, activated, target)
        lock["resolutions"][0]["capability_id"] = "technical.unreviewed"
        with self.assertRaises(CanonicalBridgeError) as lock_error:
            apply_resolution_to_ir(bridge.canonical_ir, reviewed, registry, lock)
        self.assertEqual(
            codes(lock_error.exception),
            {DiagnosticCode.PRODUCT_CONTRACT_INVALID},
        )

        lock = resolve_reviewed_needs(reviewed, registry, activated, target)
        lock["resolutions"][0]["capability_id"] = "technical.unreviewed"
        lock["content_digest"] = content_digest(lock)
        with self.assertRaises(CanonicalBridgeError) as resealed_lock_error:
            apply_resolution_to_ir(bridge.canonical_ir, reviewed, registry, lock)
        self.assertEqual(
            codes(resealed_lock_error.exception),
            {DiagnosticCode.PRODUCT_CONTRACT_INVALID},
        )

    def test_unit_status_target_and_scope_mismatches_fail_closed(self):
        *_, reviewed, registry, activated, target = inputs()
        mutations = (
            lambda p: p["needs"][0]["outputs"][0].update({"unit": "days"}),
            lambda p: p["needs"][0]["required_statuses"].pop(),
            lambda p: p["needs"][0].update({"target_profile": "cht-core-4.22@1.0.0"}),
            lambda p: p["needs"][0].update({"subject_scope": "household"}),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                changed = mutate_reviewed(reviewed, mutate)
                with self.assertRaises(CanonicalBridgeError) as raised:
                    resolve_reviewed_needs(changed, registry, activated, target)
                self.assertIn(DiagnosticCode.CAPABILITY_NEED_CONTRACT_MISMATCH, codes(raised.exception))

    def test_multiple_exact_matches_are_ambiguous(self):
        *_, reviewed, registry, activated, target = inputs()
        payload = registry.model_dump(mode="json")
        duplicate = deepcopy(payload["capability_registry"]["capabilities"][0])
        duplicate["id"] = "technical.gestational-age.alternative"
        duplicate["content_digest"] = "sha256:" + "0" * 64
        payload["capability_registry"]["capabilities"].append(duplicate)
        payload = seal_registry_set_v2(payload)
        governance = deepcopy(payload["capability_governance"]["entries"][0])
        governance["capability_id"] = duplicate["id"]
        governance["capability_content_digest"] = payload["capability_registry"]["capabilities"][1]["content_digest"]
        governance["content_digest"] = "sha256:" + "0" * 64
        payload["capability_governance"]["entries"].append(governance)
        ambiguous_registry = parse_registry_set_v2(seal_registry_set_v2(payload))
        ambiguous_activated = activated.model_copy(
            update={"registry_set_digest": ambiguous_registry.content_digest}
        )
        ambiguous_target = ambiguous_registry.target_profile
        with self.assertRaises(CanonicalBridgeError) as raised:
            resolve_reviewed_needs(
                reviewed,
                ambiguous_registry,
                ambiguous_activated,
                ambiguous_target,
            )
        self.assertEqual(codes(raised.exception), {DiagnosticCode.CAPABILITY_NEED_AMBIGUOUS})

    def test_release_and_target_artifacts_must_match_exactly(self):
        *_, reviewed, registry, activated, target = inputs()
        wrong_release = activated.model_copy(update={"registry_set_digest": "sha256:" + "f" * 64})
        with self.assertRaises(CanonicalBridgeError) as release_error:
            resolve_reviewed_needs(reviewed, registry, wrong_release, target)
        self.assertEqual(codes(release_error.exception), {DiagnosticCode.REGISTRY_RELEASE_MISMATCH})
        wrong_target = target.model_copy(update={"version": "1.0.1"})
        with self.assertRaises(CanonicalBridgeError) as target_error:
            resolve_reviewed_needs(reviewed, registry, activated, wrong_target)
        self.assertEqual(codes(target_error.exception), {DiagnosticCode.REGISTRY_RELEASE_MISMATCH})


class WS5CommandAndTracerTests(unittest.TestCase):
    def test_two_root_command_runs_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            arguments = [
                "bridge-product",
                str(EXAMPLES / "product-clinical-logic.json"),
                str(EXAMPLES / "candidate-capability-needs.json"),
                str(EXAMPLES / "product-canonical-adapter.json"),
                str(TRACER / "local-data-bindings.json"),
                str(EXAMPLES / "reviewed-capability-needs.json"),
                str(GOVERNED),
                str(EXAMPLES / "synthetic-activated-release.json"),
                str(EXAMPLES / "target-profile.json"),
            ]
            self.assertEqual(main([*arguments, str(root / "one")]), 0)
            self.assertEqual(main([*arguments, str(root / "two")]), 0)
            for name in ("canonical-ir.json", "loss-report.json", "resolution-lock.json"):
                self.assertEqual((root / "one" / name).read_bytes(), (root / "two" / name).read_bytes())

    def test_generated_ir_compiles_through_ws2_tracer_path_at_e2(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = write_ws5_package(
                product_logic_path=EXAMPLES / "product-clinical-logic.json",
                source_candidate_path=EXAMPLES / "candidate-capability-needs.json",
                adapter_path=EXAMPLES / "product-canonical-adapter.json",
                local_data_bindings_path=TRACER / "local-data-bindings.json",
                reviewed_needs_path=EXAMPLES / "reviewed-capability-needs.json",
                registry_set_path=GOVERNED,
                activated_release_path=EXAMPLES / "synthetic-activated-release.json",
                target_profile_path=EXAMPLES / "target-profile.json",
                output_dir=root / "ws5",
            )
            tracer_examples = root / "tracer-examples"
            shutil.copytree(TRACER, tracer_examples)
            (tracer_examples / "tracer.ir.json").write_text(
                json.dumps(package.canonical_ir, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            build = build_tracer(
                root / "tracer-output",
                examples_dir=tracer_examples,
                evidence_manifest=root / "tracer-evidence.json",
            )
            self.assertEqual(build.deterministic["harness"]["status"], "pass")
            self.assertEqual(build.deterministic["oracle"]["status"], "pass")

    def test_failed_product_conversion_writes_only_the_loss_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product = load(EXAMPLES / "product-clinical-logic.json")
            product["modules"] = [{"clinical_rule": "would require clinical inference"}]
            product_path = root / "unsupported-product.json"
            product_path.write_text(
                json.dumps(product, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            output = root / "output"
            with self.assertRaises(CanonicalBridgeError):
                write_ws5_package(
                    product_logic_path=product_path,
                    source_candidate_path=EXAMPLES / "candidate-capability-needs.json",
                    adapter_path=EXAMPLES / "product-canonical-adapter.json",
                    local_data_bindings_path=TRACER / "local-data-bindings.json",
                    reviewed_needs_path=EXAMPLES / "reviewed-capability-needs.json",
                    registry_set_path=GOVERNED,
                    activated_release_path=EXAMPLES / "synthetic-activated-release.json",
                    target_profile_path=EXAMPLES / "target-profile.json",
                    output_dir=output,
                )
            report = load(output / "loss-report.json")
            self.assertEqual(report["status"], "blocked")
            self.assertFalse((output / "canonical-ir.json").exists())
            self.assertFalse((output / "resolution-lock.json").exists())

    def test_contract_schemas_are_strict_and_match_runtime_roots(self):
        pairs = (
            ("product-canonical-adapter.schema.json", ProductCanonicalAdapter),
            ("reviewed-capability-needs.schema.json", ReviewedCapabilityNeeds),
        )
        for name, model in pairs:
            schema = load(ROOT / "contracts" / name)
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(set(schema["required"]), set(model.model_fields))
            self.assertEqual(set(schema["properties"]), set(model.model_fields))
        for name in (
            "product-canonical-loss-report.schema.json",
            "capability-resolution-lock.schema.json",
        ):
            schema = load(ROOT / "contracts" / name)
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")

if __name__ == "__main__":
    unittest.main()
