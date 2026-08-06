from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.canonical_bridge import write_ws5_package
from chw_navigator.cht_production import (
    CHTProductionError,
    apply_runtime_bindings,
    build_cht_production_bundle,
    inspect_production_dependencies,
    lower_registered_capabilities,
    load_runtime_bindings,
    validate_capability_invocations,
)
from chw_navigator.cht_backend import build_cht_lowering_plan
from chw_navigator.cht_local_data import load_cht_local_data_registry
from chw_navigator.cht_tasks import load_cht_task_bindings
from chw_navigator.cht_task_composer import extract_task_identities
from chw_navigator.cli import main
from chw_navigator.clinical_ir import ClinicalIRDocument
from chw_navigator.diagnostics import DiagnosticCode
from chw_navigator.registry_governance import load_registry_set_v2
from chw_navigator.registry_set import ImplementationBinding
from chw_navigator.registry_set import content_digest


WS5 = ROOT / "examples" / "ws5"
WS6 = ROOT / "examples" / "ws6"
TRACER = ROOT / "examples" / "tracer"
GOVERNED = ROOT / "contracts" / "examples" / "governance" / "valid-registry-set-v2.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class CHTProductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.ws5 = cls.root / "ws5"
        write_ws5_package(
            product_logic_path=WS5 / "product-clinical-logic.json",
            source_candidate_path=WS5 / "candidate-capability-needs.json",
            adapter_path=WS5 / "product-canonical-adapter.json",
            local_data_bindings_path=TRACER / "local-data-bindings.json",
            reviewed_needs_path=WS5 / "reviewed-capability-needs.json",
            registry_set_path=GOVERNED,
            activated_release_path=WS5 / "synthetic-activated-release.json",
            target_profile_path=WS5 / "target-profile.json",
            output_dir=cls.ws5,
        )
        cls.build = cls.build_to(cls.root / "ws6")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    @classmethod
    def build_to(cls, output: Path):
        return build_cht_production_bundle(
            canonical_ir_path=cls.ws5 / "canonical-ir.json",
            resolution_lock_path=cls.ws5 / "resolution-lock.json",
            registry_set_path=GOVERNED,
            activated_release_path=WS5 / "synthetic-activated-release.json",
            target_profile_path=WS5 / "target-profile.json",
            task_bindings_path=TRACER / "task-bindings.json",
            local_data_bindings_path=TRACER / "local-data-bindings.json",
            runtime_bindings_path=WS6 / "runtime-bindings.json",
            existing_tasks_path=TRACER / "existing-tasks.js",
            output_dir=output,
        )

    def test_general_lowerer_source_has_no_tracer_capability_or_output_names(self) -> None:
        source = (SRC / "chw_navigator" / "cht_production.py").read_text(encoding="utf-8")
        for forbidden in (
            "technical.gestational-age.naegele",
            '"ga_weeks"',
            '"ga_days_remainder"',
            '"edd"',
        ):
            self.assertNotIn(forbidden, source)
        xform = self.build.adapter.form_xform_path.read_text(encoding="utf-8")
        self.assertIn("cap_gestational_age_naegele_output_00", xform)
        self.assertIn('nodeset="/data/st_ga_weeks" type="int"', xform)
        self.assertIn('nodeset="/data/st_edd" type="date"', xform)

    def test_only_referenced_registry_capability_is_selected_and_emitted(self) -> None:
        document = ClinicalIRDocument.from_dict(load(self.ws5 / "canonical-ir.json"))
        registry = load_registry_set_v2(GOVERNED)
        capability = registry.capability_registry.capabilities[0]
        selected = validate_capability_invocations(
            document,
            {capability.id: capability, "technical.unused": capability},
        )
        self.assertEqual([capability.id], [item.id for item in selected])
        self.assertEqual(["gestational-age-from-lmp.js"], self.build.deterministic["emitted_extensions"])

    def test_unreviewed_implementation_binding_has_stable_diagnostic(self) -> None:
        document = ClinicalIRDocument.from_dict(load(self.ws5 / "canonical-ir.json"))
        registry = load_registry_set_v2(GOVERNED)
        capability = registry.capability_registry.capabilities[0].model_copy(
            update={
                "implementation_binding": ImplementationBinding(
                    kind="python_cht_extension",
                    python_module="synthetic.unreviewed",
                    python_symbol="unreviewed",
                    cht_extension_module="unreviewed.js",
                )
            }
        )
        plan = build_cht_lowering_plan(
            document,
            task_bindings=load_cht_task_bindings(TRACER / "task-bindings.json"),
            local_data_registry=load_cht_local_data_registry(TRACER / "local-data-bindings.json"),
            form_context="contact",
        )
        runtime = load_runtime_bindings(WS6 / "runtime-bindings.json")
        apply_runtime_bindings(plan, document, runtime, registry.target_profile)
        with self.assertRaises(CHTProductionError) as raised:
            lower_registered_capabilities(
                plan,
                document,
                (capability,),
                registry.target_profile,
            )
        self.assertEqual(
            DiagnosticCode.CHT_CAPABILITY_LOWERER_UNBOUND,
            raised.exception.diagnostics[0].code,
        )

    def test_python_composition_preserves_unrelated_rules_and_exact_rollback(self) -> None:
        existing = (TRACER / "existing-tasks.js").read_bytes()
        composed = self.build.composed_tasks_path.read_text(encoding="utf-8")
        self.assertIn("existing-unrelated-supervision-task", composed)
        self.assertIn("CHW-NAVIGATOR-GENERATED-RULES-BEGIN", composed)
        self.assertEqual(existing, self.build.rollback_tasks_path.read_bytes())
        self.assertTrue(self.build.deterministic["composition"]["second_composition_byte_identical"])

    def test_typescript_remains_a_differential_oracle_only(self) -> None:
        runner_path = ROOT / "integration" / "typescript_oracle_runner.py"
        spec = importlib.util.spec_from_file_location("ws6_ts_oracle", runner_path)
        assert spec is not None and spec.loader is not None
        oracle = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(oracle)
        generated = self.build.adapter.tasks_js_path.read_text(encoding="utf-8")
        existing = (TRACER / "existing-tasks.js").read_text(encoding="utf-8")
        oracle_result = oracle.compose_tasks_js(existing, generated)
        python_names = [
            item.name for item in extract_task_identities(generated)
        ]
        oracle_names = [
            item["name"] for item in oracle_result["evidence"]["ruleIdentities"]
        ]
        self.assertEqual(python_names, oracle_names)
        self.assertIn("existing-unrelated-supervision-task", oracle_result["content"])
        self.assertNotIn("typescript_oracle", json.dumps(self.build.deterministic))

    def test_production_dependency_graph_does_not_require_node(self) -> None:
        result = inspect_production_dependencies()
        self.assertEqual("pass", result["status"])
        self.assertFalse(result["node_required"])
        self.assertEqual([], result["forbidden_dependency_findings"])
        self.assertEqual(
            {
                "chw_navigator.cht_backend",
                "chw_navigator.cht_evidence",
                "chw_navigator.cht_local_data",
                "chw_navigator.cht_production",
                "chw_navigator.cht_special_functions",
                "chw_navigator.cht_task_composer",
                "chw_navigator.cht_tasks",
                "chw_navigator.queued_topology",
            },
            set(result["inspected_modules"]),
        )

    def test_all_registered_statuses_are_required(self) -> None:
        payload = load(self.ws5 / "canonical-ir.json")
        decision = payload["decisions"]["d_gestational_age_naegele_status"]
        decision["rules"] = [
            item for item in decision["rules"] if "execution_failure" not in item["id"]
        ]
        document = ClinicalIRDocument.from_dict(payload)
        registry = load_registry_set_v2(GOVERNED)
        capabilities = {item.id: item for item in registry.capability_registry.capabilities}
        with self.assertRaises(CHTProductionError) as raised:
            validate_capability_invocations(document, capabilities)
        self.assertIn(
            DiagnosticCode.STATUS_COVERAGE_INCOMPLETE,
            {item.code for item in raised.exception.diagnostics},
        )

    def test_duplicate_capability_invocation_fails_instead_of_lowering_only_the_first(self) -> None:
        payload = load(self.ws5 / "canonical-ir.json")
        original_id = next(
            key for key, value in payload["actions"].items() if value["kind"] == "invoke_capability"
        )
        duplicate = deepcopy(payload["actions"][original_id])
        duplicate["id"] = "a_duplicate_capability_invocation"
        payload["actions"][duplicate["id"]] = duplicate
        document = ClinicalIRDocument.from_dict(payload)
        registry = load_registry_set_v2(GOVERNED)
        capabilities = {item.id: item for item in registry.capability_registry.capabilities}
        with self.assertRaises(CHTProductionError) as raised:
            validate_capability_invocations(document, capabilities)
        self.assertIn(
            DiagnosticCode.CAPABILITY_INVOCATION_INVALID,
            {item.code for item in raised.exception.diagnostics},
        )

    def test_status_coverage_requires_an_exact_structural_variable_reference(self) -> None:
        payload = load(self.ws5 / "canonical-ir.json")
        action = next(
            value for value in payload["actions"].values() if value["kind"] == "invoke_capability"
        )
        status_id = action["status_target_var"]
        shadow_id = status_id + "_shadow"
        payload["variables"][shadow_id] = deepcopy(payload["variables"][status_id])

        def replace_reference(value):
            if isinstance(value, dict):
                return {
                    key: shadow_id if key == "id" and item == status_id else replace_reference(item)
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [replace_reference(item) for item in value]
            return value

        for decision in payload["decisions"].values():
            decision["rules"] = [
                {**rule, "when": replace_reference(rule["when"])} for rule in decision["rules"]
            ]
            decision["inputs_used"] = [
                shadow_id if item == status_id else item for item in decision["inputs_used"]
            ]
        document = ClinicalIRDocument.from_dict(payload)
        registry = load_registry_set_v2(GOVERNED)
        capabilities = {item.id: item for item in registry.capability_registry.capabilities}
        with self.assertRaises(CHTProductionError) as raised:
            validate_capability_invocations(document, capabilities)
        self.assertIn(
            DiagnosticCode.STATUS_COVERAGE_INCOMPLETE,
            {item.code for item in raised.exception.diagnostics},
        )

    def test_duplicate_resolution_entries_fail_even_with_a_valid_outer_digest(self) -> None:
        lock = load(self.ws5 / "resolution-lock.json")
        lock["resolutions"].append(deepcopy(lock["resolutions"][0]))
        lock["content_digest"] = content_digest(lock)
        lock_path = self.root / "duplicate-resolution-lock.json"
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        with self.assertRaises(CHTProductionError) as raised:
            build_cht_production_bundle(
                canonical_ir_path=self.ws5 / "canonical-ir.json",
                resolution_lock_path=lock_path,
                registry_set_path=GOVERNED,
                activated_release_path=WS5 / "synthetic-activated-release.json",
                target_profile_path=WS5 / "target-profile.json",
                task_bindings_path=TRACER / "task-bindings.json",
                local_data_bindings_path=TRACER / "local-data-bindings.json",
                runtime_bindings_path=WS6 / "runtime-bindings.json",
                existing_tasks_path=TRACER / "existing-tasks.js",
                output_dir=self.root / "duplicate-resolution",
            )
        self.assertEqual(
            DiagnosticCode.REGISTRY_RELEASE_MISMATCH,
            raised.exception.diagnostics[0].code,
        )

    def test_resolution_lock_target_and_runtime_binding_mismatches_fail_closed(self) -> None:
        cases: list[tuple[str, Path]] = []
        lock = load(self.ws5 / "resolution-lock.json")
        lock["release_digest"] = "sha256:" + "f" * 64
        lock_path = self.root / "bad-lock.json"
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        cases.append(("lock", lock_path))

        runtime = load(WS6 / "runtime-bindings.json")
        runtime["target_cht_version"] = "4.22.0"
        runtime_path = self.root / "bad-runtime.json"
        runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
        cases.append(("runtime", runtime_path))

        for name, path in cases:
            with self.subTest(name=name):
                kwargs = {
                    "canonical_ir_path": self.ws5 / "canonical-ir.json",
                    "resolution_lock_path": path if name == "lock" else self.ws5 / "resolution-lock.json",
                    "registry_set_path": GOVERNED,
                    "activated_release_path": WS5 / "synthetic-activated-release.json",
                    "target_profile_path": WS5 / "target-profile.json",
                    "task_bindings_path": TRACER / "task-bindings.json",
                    "local_data_bindings_path": TRACER / "local-data-bindings.json",
                    "runtime_bindings_path": path if name == "runtime" else WS6 / "runtime-bindings.json",
                    "existing_tasks_path": TRACER / "existing-tasks.js",
                    "output_dir": self.root / f"bad-{name}",
                }
                with self.assertRaises(CHTProductionError) as raised:
                    build_cht_production_bundle(**kwargs)
                if name == "runtime":
                    self.assertEqual(
                        DiagnosticCode.CHT_RUNTIME_BINDING_INVALID,
                        raised.exception.diagnostics[0].code,
                    )

    def test_two_clean_builds_are_deterministic_and_evidence_is_not_inflated(self) -> None:
        second = self.build_to(self.root / "ws6-second")
        self.assertEqual(self.build.deterministic, second.deterministic)
        evidence = load(self.build.evidence_manifest_path)
        self.assertEqual("E2", evidence["evidence_level"])
        self.assertFalse(evidence["deployment_ready"])
        self.assertEqual(
            {"4.22.0", "5.2.0"},
            {item["profile"] for item in evidence["environment_checks"]},
        )
        self.assertTrue(all(item["status"] == "not_run" for item in evidence["environment_checks"]))

    def test_root_command_writes_the_same_bounded_bundle(self) -> None:
        output = self.root / "cli"
        result = main(
            [
                "build-cht-production",
                str(self.ws5 / "canonical-ir.json"),
                str(self.ws5 / "resolution-lock.json"),
                str(GOVERNED),
                str(WS5 / "synthetic-activated-release.json"),
                str(WS5 / "target-profile.json"),
                str(TRACER / "task-bindings.json"),
                str(TRACER / "local-data-bindings.json"),
                str(WS6 / "runtime-bindings.json"),
                str(TRACER / "existing-tasks.js"),
                str(output),
            ]
        )
        self.assertEqual(0, result)
        self.assertTrue((output / "evidence-manifest.json").is_file())
        self.assertEqual(
            self.build.composed_tasks_path.read_bytes(),
            (output / "tasks.js").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
