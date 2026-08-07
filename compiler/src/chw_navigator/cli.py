from __future__ import annotations

import argparse
import json
import sys
from json import JSONDecodeError
from pathlib import Path

from .bundles import BundleBuildError, create_bundle
from .catalogs import CatalogLoadError, compose_document_from_catalogs
from .change_control import ChangeReviewBuildError, create_change_review_package, load_change_memo
from .canonical_bridge import CanonicalBridgeError, write_ws5_package
from .clinical_ir import ClinicalIRDocument
from .cht_backend import build_cht_lowering_plan, write_cht_adapter_bundle
from .cht_local_data import CHTLocalDataLoweringError, load_cht_local_data_registry
from .cht_production import CHTProductionError, build_cht_production_bundle
from .cht_tasks import CHTTaskLoweringError, load_cht_task_bindings
from .compare import (
    ComparisonError,
    build_comparison_log,
    build_z3_checks_log,
    compare_backends,
    load_patient_cases,
)
from .dmn import DMNImportError, import_dmn_decisions
from .evaluator import EvaluationError, evaluate_document
from .equivalence import build_case_suite_equivalence_report
from .json_schema_export import write_json_schemas
from .mermaid_backend import MermaidOptions, build_mermaid_artifact
from .quality_checks import run_quality_checks
from .registry_match import RegistryMatchError, write_registry_match_review
from .synthetic_registry_pilot import SyntheticRegistryPilotError
from .synthetic_registry_pilot_example import write_synthetic_registry_pilot_example
from .staged_lint import (
    lint_ir_document,
    lint_mermaid_artifact,
    lint_smt_artifact,
    lint_xlsform_artifacts,
    preflight_catalog_bundle,
    preflight_source_artifact,
    render_stage_lint_report,
)
from .validator import validate_document
from .xlsform_import import XLSFormImportError, import_xlsform_files_detailed
from .xlsform_proof import build_xlsform_roundtrip_proof
from .z3_backend import (
    Z3BackendUnavailable,
    Z3LoweringError,
    analyze_document,
    build_z3_model,
    compare_smt2_file,
    export_smt2,
    generate_patient_for_rule,
    write_smt2,
)
from .xlsform_backend import XLSFormBuildError, build_xlsform, write_xlsform_csvs


class CLIError(Exception):
    """Raised when CLI inputs cannot be loaded or parsed safely."""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chw-nav")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="validate a Clinical IR JSON file")
    validate_parser.add_argument("ir_path")

    schema_parser = subparsers.add_parser(
        "write-json-schemas",
        help="write machine-checked JSON Schema files for supported JSON artifact families",
    )
    schema_parser.add_argument("output_dir")

    source_lint_parser = subparsers.add_parser("preflight-source", help="run source-artifact preflight lint")
    source_lint_parser.add_argument("artifact_type", choices=["variable_catalog", "predicate_catalog", "phrase_bank", "dmn", "patient_cases"])
    source_lint_parser.add_argument("path")
    source_lint_parser.add_argument("--output", dest="output_path")

    bundle_lint_parser = subparsers.add_parser(
        "preflight-bundle",
        help="run cross-file preflight lint across metadata, catalogs, and optional DMN",
    )
    bundle_lint_parser.add_argument("metadata_path")
    bundle_lint_parser.add_argument("variable_catalog_path")
    bundle_lint_parser.add_argument("predicate_catalog_path")
    bundle_lint_parser.add_argument("phrase_bank_path")
    bundle_lint_parser.add_argument("--dmn", dest="dmn_path")
    bundle_lint_parser.add_argument("--output", dest="output_path")

    ir_lint_parser = subparsers.add_parser("lint-ir", help="run compiled IR validation plus IR lint")
    ir_lint_parser.add_argument("ir_path")
    ir_lint_parser.add_argument("--output", dest="output_path")

    compose_parser = subparsers.add_parser(
        "compose-ir",
        help="compose a base Clinical IR JSON document from standalone metadata, variable, predicate, and phrase catalogs",
    )
    compose_parser.add_argument("metadata_path")
    compose_parser.add_argument("variable_catalog_path")
    compose_parser.add_argument("predicate_catalog_path")
    compose_parser.add_argument("phrase_bank_path")
    compose_parser.add_argument("--output", dest="output_path")

    evaluate_parser = subparsers.add_parser("evaluate", help="evaluate a Clinical IR JSON file against one patient input")
    evaluate_parser.add_argument("ir_path")
    evaluate_parser.add_argument("patient_path")

    xlsform_import_parser = subparsers.add_parser(
        "import-xlsform",
        help="import a supported XLSForm survey/choices pair into Clinical IR",
    )
    xlsform_import_parser.add_argument("survey_path")
    xlsform_import_parser.add_argument("choices_path")
    xlsform_import_parser.add_argument("--guideline-id", dest="guideline_id")
    xlsform_import_parser.add_argument("--output", dest="output_path")

    xlsform_proof_parser = subparsers.add_parser(
        "prove-xlsform",
        help="import a supported XLSForm, compare it to the original workbook and optional reference IR, and write a round-trip proof package",
    )
    xlsform_proof_parser.add_argument("survey_path")
    xlsform_proof_parser.add_argument("choices_path")
    xlsform_proof_parser.add_argument("output_dir")
    xlsform_proof_parser.add_argument("--guideline-id", dest="guideline_id")
    xlsform_proof_parser.add_argument("--reference-ir", dest="reference_ir_path")
    xlsform_proof_parser.add_argument("--patients", dest="patient_path")

    dmn_parser = subparsers.add_parser("import-dmn", help="replace decisions in a base Clinical IR with decisions parsed from DMN")
    dmn_parser.add_argument("base_ir_path")
    dmn_parser.add_argument("dmn_path")
    dmn_parser.add_argument("--output", dest="output_path")

    z3_parser = subparsers.add_parser("z3-summary", help="lower a Clinical IR JSON file into Z3 and report the solver state")
    z3_parser.add_argument("ir_path")

    checks_parser = subparsers.add_parser("z3-checks", help="run formal QA checks and return witness patients when applicable")
    checks_parser.add_argument("ir_path")

    patient_parser = subparsers.add_parser("z3-rule-patient", help="generate one witness patient that fires the named rule")
    patient_parser.add_argument("ir_path")
    patient_parser.add_argument("rule_id")

    smt2_parser = subparsers.add_parser("export-smt2", help="export the current Z3 lowering as SMT-LIB 2")
    smt2_parser.add_argument("ir_path")
    smt2_parser.add_argument("--output", dest="output_path")

    compare_smt2_parser = subparsers.add_parser("compare-smt2", help="compare an SMT-LIB candidate against the reference interpreter")
    compare_smt2_parser.add_argument("ir_path")
    compare_smt2_parser.add_argument("smt2_path")
    compare_smt2_parser.add_argument("--patients", dest="patient_path")

    xlsform_parser = subparsers.add_parser("build-xlsform", help="build survey.csv and choices.csv for the supported XLSForm subset")
    xlsform_parser.add_argument("ir_path")
    xlsform_parser.add_argument("output_dir")

    cht_parser = subparsers.add_parser(
        "build-cht",
        help="build CHT XLSForm task-intent source, tasks.js, manifests, and optional reviewed special functions",
    )
    cht_parser.add_argument("ir_path")
    cht_parser.add_argument("task_bindings_path")
    cht_parser.add_argument("output_dir")
    cht_parser.add_argument(
        "--include-reviewed-special-functions",
        action="store_true",
        help="also emit reviewed special functions for the task-binding file's exact CHT version",
    )
    cht_parser.add_argument(
        "--local-data-bindings",
        dest="local_data_bindings_path",
        help="versioned CHT local-data binding registry used to lower read_local_data/read_history actions",
    )
    cht_parser.add_argument(
        "--form-context",
        choices=("contact", "task", "reports"),
        default="contact",
        help="how the generated app form will be launched; used to validate local-data availability",
    )

    quality_parser = subparsers.add_parser(
        "quality-check",
        help="compile XLSForm, Mermaid, and SMT artifacts from IR and write a local quality-check package",
    )
    quality_parser.add_argument("ir_path")
    quality_parser.add_argument("output_dir")
    quality_parser.add_argument("--patients", dest="patient_path")

    xlsform_lint_parser = subparsers.add_parser("lint-xlsform", help="run backend-specific lint on survey.csv and choices.csv")
    xlsform_lint_parser.add_argument("survey_path")
    xlsform_lint_parser.add_argument("choices_path")
    xlsform_lint_parser.add_argument("--output", dest="output_path")

    mermaid_parser = subparsers.add_parser("build-mermaid", help="build a Mermaid flowchart from canonical Clinical IR")
    mermaid_parser.add_argument("ir_path")
    mermaid_parser.add_argument("--output", dest="output_path")
    mermaid_parser.add_argument("--direction", dest="direction", default="LR")
    mermaid_parser.add_argument("--font-size", dest="font_size", type=int, default=24)

    mermaid_lint_parser = subparsers.add_parser("lint-mermaid", help="run backend-specific lint on canonical or candidate Mermaid text")
    mermaid_lint_parser.add_argument("ir_path")
    mermaid_lint_parser.add_argument("--candidate", dest="candidate_path")
    mermaid_lint_parser.add_argument("--output", dest="output_path")

    compare_parser = subparsers.add_parser("compare", help="compare interpreter, DMN-imported IR, XLSForm runtime, and Z3 witnesses")
    compare_parser.add_argument("ir_path")
    compare_parser.add_argument("--dmn", dest="dmn_path")
    compare_parser.add_argument("--patients", dest="patient_path")

    equivalence_parser = subparsers.add_parser(
        "build-equivalence-report",
        help="compare two IR documents over an explicit patient suite and write a bounded clinical-equivalence report",
    )
    equivalence_parser.add_argument("baseline_ir_path")
    equivalence_parser.add_argument("candidate_ir_path")
    equivalence_parser.add_argument("patient_path")
    equivalence_parser.add_argument("output_dir")

    smt_lint_parser = subparsers.add_parser("lint-smt2", help="run backend-specific lint on canonical or candidate SMT-LIB")
    smt_lint_parser.add_argument("ir_path")
    smt_lint_parser.add_argument("--candidate", dest="candidate_path")
    smt_lint_parser.add_argument("--output", dest="output_path")

    bundle_parser = subparsers.add_parser(
        "create-bundle",
        help="create an immutable bundle with source inputs, generated artifacts, and baseline comparison reports",
    )
    bundle_parser.add_argument("ir_path")
    bundle_parser.add_argument("dmn_path")
    bundle_parser.add_argument("--patients", dest="patient_path")
    bundle_parser.add_argument("--bundle-root", dest="bundle_root", default="generated\\bundles")
    bundle_parser.add_argument("--label", dest="source_label")

    change_review_parser = subparsers.add_parser(
        "build-change-review",
        help="create a change-review package from a memo, baseline IR, updated IR, and optional cases/DMN files",
    )
    change_review_parser.add_argument("memo_path")
    change_review_parser.add_argument("baseline_ir_path")
    change_review_parser.add_argument("updated_ir_path")
    change_review_parser.add_argument("review_root")
    change_review_parser.add_argument("--patients", dest="patient_path")
    change_review_parser.add_argument("--baseline-dmn", dest="baseline_dmn_path")
    change_review_parser.add_argument("--updated-dmn", dest="updated_dmn_path")

    bridge_parser = subparsers.add_parser(
        "bridge-product",
        help="convert bounded Product logic and exactly resolve reviewed capability needs",
    )
    bridge_parser.add_argument("product_logic_path")
    bridge_parser.add_argument("source_candidate_path")
    bridge_parser.add_argument("adapter_path")
    bridge_parser.add_argument("local_data_bindings_path")
    bridge_parser.add_argument("reviewed_needs_path")
    bridge_parser.add_argument("registry_set_path")
    bridge_parser.add_argument("activated_release_path")
    bridge_parser.add_argument("target_profile_path")
    bridge_parser.add_argument("output_dir")

    match_review_parser = subparsers.add_parser(
        "build-registry-match-review",
        help="validate a registry-visible AI proposal and write a non-executable human review package",
    )
    match_review_parser.add_argument("source_candidate_path")
    match_review_parser.add_argument("proposal_path")
    match_review_parser.add_argument("product_logic_path")
    match_review_parser.add_argument("registry_set_path")
    match_review_parser.add_argument("local_data_bindings_path")
    match_review_parser.add_argument("output_path")

    pilot_parser = subparsers.add_parser(
        "run-synthetic-registry-pilot",
        help="run the isolated three-case software pilot and emit only watermarked non-clinical artifacts",
    )
    pilot_parser.add_argument("simulated_catalogue_path")
    pilot_parser.add_argument("output_dir")

    production_parser = subparsers.add_parser(
        "build-cht-production",
        help="build the bounded WS6 Python-owned CHT bundle from governed WS5 outputs",
    )
    production_parser.add_argument("canonical_ir_path")
    production_parser.add_argument("resolution_lock_path")
    production_parser.add_argument("registry_set_path")
    production_parser.add_argument("activated_release_path")
    production_parser.add_argument("target_profile_path")
    production_parser.add_argument("task_bindings_path")
    production_parser.add_argument("local_data_bindings_path")
    production_parser.add_argument("runtime_bindings_path")
    production_parser.add_argument("existing_tasks_path")
    production_parser.add_argument("output_dir")

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.command == "validate":
        return _handle_validate(Path(args.ir_path))
    if args.command == "write-json-schemas":
        return _handle_write_json_schemas(Path(args.output_dir))
    if args.command == "preflight-source":
        return _handle_preflight_source(args.artifact_type, Path(args.path), args.output_path)
    if args.command == "preflight-bundle":
        return _handle_preflight_bundle(
            Path(args.metadata_path),
            Path(args.variable_catalog_path),
            Path(args.predicate_catalog_path),
            Path(args.phrase_bank_path),
            args.dmn_path,
            args.output_path,
        )
    if args.command == "lint-ir":
        return _handle_lint_ir(Path(args.ir_path), args.output_path)
    if args.command == "compose-ir":
        return _handle_compose_ir(
            Path(args.metadata_path),
            Path(args.variable_catalog_path),
            Path(args.predicate_catalog_path),
            Path(args.phrase_bank_path),
            args.output_path,
        )
    if args.command == "evaluate":
        return _handle_evaluate(Path(args.ir_path), Path(args.patient_path))
    if args.command == "import-xlsform":
        return _handle_import_xlsform(
            Path(args.survey_path),
            Path(args.choices_path),
            args.guideline_id,
            args.output_path,
        )
    if args.command == "prove-xlsform":
        return _handle_prove_xlsform(
            Path(args.survey_path),
            Path(args.choices_path),
            Path(args.output_dir),
            args.guideline_id,
            args.reference_ir_path,
            args.patient_path,
        )
    if args.command == "import-dmn":
        return _handle_import_dmn(Path(args.base_ir_path), Path(args.dmn_path), args.output_path)
    if args.command == "z3-summary":
        return _handle_z3_summary(Path(args.ir_path))
    if args.command == "z3-checks":
        return _handle_z3_checks(Path(args.ir_path))
    if args.command == "z3-rule-patient":
        return _handle_z3_rule_patient(Path(args.ir_path), args.rule_id)
    if args.command == "export-smt2":
        return _handle_export_smt2(Path(args.ir_path), args.output_path)
    if args.command == "compare-smt2":
        return _handle_compare_smt2(Path(args.ir_path), args.smt2_path, args.patient_path)
    if args.command == "build-xlsform":
        return _handle_build_xlsform(Path(args.ir_path), args.output_dir)
    if args.command == "build-cht":
        return _handle_build_cht(
            Path(args.ir_path),
            Path(args.task_bindings_path),
            Path(args.output_dir),
            args.include_reviewed_special_functions,
            args.local_data_bindings_path,
            args.form_context,
        )
    if args.command == "quality-check":
        return _handle_quality_check(Path(args.ir_path), Path(args.output_dir), args.patient_path)
    if args.command == "lint-xlsform":
        return _handle_lint_xlsform(Path(args.survey_path), Path(args.choices_path), args.output_path)
    if args.command == "build-mermaid":
        return _handle_build_mermaid(Path(args.ir_path), args.output_path, args.direction, args.font_size)
    if args.command == "lint-mermaid":
        return _handle_lint_mermaid(Path(args.ir_path), args.candidate_path, args.output_path)
    if args.command == "compare":
        return _handle_compare(Path(args.ir_path), args.dmn_path, args.patient_path)
    if args.command == "build-equivalence-report":
        return _handle_build_equivalence_report(
            Path(args.baseline_ir_path),
            Path(args.candidate_ir_path),
            Path(args.patient_path),
            Path(args.output_dir),
        )
    if args.command == "lint-smt2":
        return _handle_lint_smt2(Path(args.ir_path), args.candidate_path, args.output_path)
    if args.command == "create-bundle":
        return _handle_create_bundle(
            Path(args.ir_path),
            Path(args.dmn_path),
            args.bundle_root,
            args.patient_path,
            args.source_label,
        )
    if args.command == "build-change-review":
        return _handle_build_change_review(
            Path(args.memo_path),
            Path(args.baseline_ir_path),
            Path(args.updated_ir_path),
            Path(args.review_root),
            args.patient_path,
            args.baseline_dmn_path,
            args.updated_dmn_path,
        )
    if args.command == "bridge-product":
        return _handle_bridge_product(
            Path(args.product_logic_path),
            Path(args.source_candidate_path),
            Path(args.adapter_path),
            Path(args.local_data_bindings_path),
            Path(args.reviewed_needs_path),
            Path(args.registry_set_path),
            Path(args.activated_release_path),
            Path(args.target_profile_path),
            Path(args.output_dir),
        )
    if args.command == "build-registry-match-review":
        return _handle_registry_match_review(
            Path(args.source_candidate_path),
            Path(args.proposal_path),
            Path(args.product_logic_path),
            Path(args.registry_set_path),
            Path(args.local_data_bindings_path),
            Path(args.output_path),
        )
    if args.command == "run-synthetic-registry-pilot":
        return _handle_synthetic_registry_pilot(
            Path(args.simulated_catalogue_path),
            Path(args.output_dir),
        )
    if args.command == "build-cht-production":
        return _handle_build_cht_production(
            Path(args.canonical_ir_path),
            Path(args.resolution_lock_path),
            Path(args.registry_set_path),
            Path(args.activated_release_path),
            Path(args.target_profile_path),
            Path(args.task_bindings_path),
            Path(args.local_data_bindings_path),
            Path(args.runtime_bindings_path),
            Path(args.existing_tasks_path),
            Path(args.output_dir),
        )
    raise AssertionError(f"unknown command '{args.command}'")


def _handle_write_json_schemas(output_dir: Path) -> int:
    written = write_json_schemas(output_dir)
    print(f"wrote {len(written)} JSON Schema files to {output_dir}")
    for name, path in sorted(written.items()):
        print(f"- {name}: {path}")
    return 0


def _handle_bridge_product(
    product_logic_path: Path,
    source_candidate_path: Path,
    adapter_path: Path,
    local_data_bindings_path: Path,
    reviewed_needs_path: Path,
    registry_set_path: Path,
    activated_release_path: Path,
    target_profile_path: Path,
    output_dir: Path,
) -> int:
    try:
        write_ws5_package(
            product_logic_path=product_logic_path,
            source_candidate_path=source_candidate_path,
            adapter_path=adapter_path,
            local_data_bindings_path=local_data_bindings_path,
            reviewed_needs_path=reviewed_needs_path,
            registry_set_path=registry_set_path,
            activated_release_path=activated_release_path,
            target_profile_path=target_profile_path,
            output_dir=output_dir,
        )
    except CanonicalBridgeError as exc:
        print(str(exc))
        return 1
    print(f"wrote WS5 canonical IR, loss report, and resolution lock to {output_dir}")
    return 0


def _handle_registry_match_review(
    source_candidate_path: Path,
    proposal_path: Path,
    product_logic_path: Path,
    registry_set_path: Path,
    local_data_bindings_path: Path,
    output_path: Path,
) -> int:
    try:
        write_registry_match_review(
            source_candidate_path=source_candidate_path,
            proposal_path=proposal_path,
            product_logic_path=product_logic_path,
            registry_set_path=registry_set_path,
            local_data_registry_path=local_data_bindings_path,
            output_path=output_path,
        )
    except RegistryMatchError as exc:
        print(str(exc))
        return 1
    print(f"wrote non-executable registry match review to {output_path}")
    return 0


def _handle_synthetic_registry_pilot(
    simulated_catalogue_path: Path,
    output_dir: Path,
) -> int:
    try:
        report = write_synthetic_registry_pilot_example(
            simulated_catalogue_path,
            output_dir,
        )
    except (SyntheticRegistryPilotError, RegistryMatchError, OSError, json.JSONDecodeError) as exc:
        print(str(exc))
        return 1
    print("SYNTHETIC SOFTWARE PILOT ONLY — NOT FOR PATIENT CARE OR DEPLOYMENT")
    print(f"pilot status={report['overall_status']} report={output_dir / 'pilot-report.json'}")
    return 0


def _handle_build_cht_production(
    canonical_ir_path: Path,
    resolution_lock_path: Path,
    registry_set_path: Path,
    activated_release_path: Path,
    target_profile_path: Path,
    task_bindings_path: Path,
    local_data_bindings_path: Path,
    runtime_bindings_path: Path,
    existing_tasks_path: Path,
    output_dir: Path,
) -> int:
    try:
        build_cht_production_bundle(
            canonical_ir_path=canonical_ir_path,
            resolution_lock_path=resolution_lock_path,
            registry_set_path=registry_set_path,
            activated_release_path=activated_release_path,
            target_profile_path=target_profile_path,
            task_bindings_path=task_bindings_path,
            local_data_bindings_path=local_data_bindings_path,
            runtime_bindings_path=runtime_bindings_path,
            existing_tasks_path=existing_tasks_path,
            output_dir=output_dir,
        )
    except CHTProductionError as exc:
        print(str(exc))
        return 1
    print(f"wrote WS6 bounded CHT production bundle to {output_dir}")
    return 0


def _handle_compose_ir(
    metadata_path: Path,
    variable_catalog_path: Path,
    predicate_catalog_path: Path,
    phrase_bank_path: Path,
    output_path: str | None,
) -> int:
    try:
        document = compose_document_from_catalogs(
            metadata_path=metadata_path,
            variable_catalog_path=variable_catalog_path,
            predicate_catalog_path=predicate_catalog_path,
            phrase_bank_path=phrase_bank_path,
        )
    except CatalogLoadError as exc:
        print(f"catalog compose failed: {exc}")
        return 1
    rendered = json.dumps(_document_to_dict(document), indent=2, sort_keys=True)
    if output_path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
        print(f"wrote composed IR to {output_path}")
    else:
        print(rendered)
    return 0


def _handle_validate(path: Path) -> int:
    try:
        document = _load_document(path)
    except CLIError as exc:
        print(f"validation failed: {exc}")
        return 1
    errors = validate_document(document)
    if errors:
        print(f"validation failed: {len(errors)} error(s)")
        for error in errors:
            print(f"- {error.path}: {error.message}")
        return 1
    print(f"validation passed: {path}")
    return 0


def _handle_preflight_source(artifact_type: str, path: Path, output_path: str | None) -> int:
    report = preflight_source_artifact(artifact_type, path)
    rendered = render_stage_lint_report(report)
    if output_path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"wrote source preflight report to {output}")
    else:
        print(rendered, end="")
    return 0 if report.ok else 1


def _handle_preflight_bundle(
    metadata_path: Path,
    variable_catalog_path: Path,
    predicate_catalog_path: Path,
    phrase_bank_path: Path,
    dmn_path: str | None,
    output_path: str | None,
) -> int:
    report = preflight_catalog_bundle(
        metadata_path=metadata_path,
        variable_catalog_path=variable_catalog_path,
        predicate_catalog_path=predicate_catalog_path,
        phrase_bank_path=phrase_bank_path,
        dmn_path=Path(dmn_path) if dmn_path else None,
    )
    rendered = render_stage_lint_report(report)
    if output_path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report.ok else 1


def _handle_lint_ir(ir_path: Path, output_path: str | None) -> int:
    try:
        document = _load_document(ir_path)
    except CLIError as exc:
        print(f"ir lint failed: {exc}")
        return 1
    report = lint_ir_document(document, source_path=str(ir_path))
    rendered = render_stage_lint_report(report)
    if output_path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"wrote IR lint report to {output}")
    else:
        print(rendered, end="")
    return 0 if report.ok else 1


def _handle_evaluate(ir_path: Path, patient_path: Path) -> int:
    try:
        document = _load_document(ir_path)
        patient = _load_json_file(patient_path, "patient input")
    except CLIError as exc:
        print(f"evaluation failed: {exc}")
        return 1
    try:
        result = evaluate_document(
            document,
            values=dict(patient.get("values", {})),
            missing=set(patient.get("missing", [])),
        )
    except EvaluationError as exc:
        print(f"evaluation failed: {exc}")
        return 1

    print(
        json.dumps(
            {
                "predicates": result.predicates,
                "outputs": result.outputs,
                "decisions": [
                    {"decision_id": trace.decision_id, "fired_rule_id": trace.fired_rule_id}
                    for trace in result.decisions
                ],
                "invariants": result.invariants,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _handle_import_xlsform(
    survey_path: Path,
    choices_path: Path,
    guideline_id: str | None,
    output_path: str | None,
) -> int:
    try:
        imported = import_xlsform_files_detailed(
            str(survey_path),
            str(choices_path),
            guideline_id=guideline_id,
        )
    except XLSFormImportError as exc:
        print(f"xlsform import failed: {exc}")
        return 1
    document = imported.document
    rendered = json.dumps(_document_to_dict(document), indent=2, sort_keys=True)
    if output_path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
        print(f"wrote imported IR to {output_path}")
        report_output = output.with_suffix(output.suffix + ".import-report.json")
        report_output.write_text(json.dumps(_clean(imported.report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote XLSForm import report to {report_output}")
    else:
        print(
            json.dumps(
                {
                    "document": _document_to_dict(document),
                    "import_report": _clean(imported.report),
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0


def _handle_prove_xlsform(
    survey_path: Path,
    choices_path: Path,
    output_dir: Path,
    guideline_id: str | None,
    reference_ir_path: str | None,
    patient_path: str | None,
) -> int:
    try:
        reference_document = _load_document(Path(reference_ir_path)) if reference_ir_path else None
        patient_cases = load_patient_cases(patient_path) if patient_path else None
    except (CLIError, ComparisonError) as exc:
        print(f"xlsform proof setup failed: {exc}")
        return 1

    try:
        built = build_xlsform_roundtrip_proof(
            survey_path=survey_path,
            choices_path=choices_path,
            output_dir=output_dir,
            guideline_id=guideline_id,
            reference_document=reference_document,
            patient_cases=patient_cases,
        )
    except (XLSFormImportError, ComparisonError, XLSFormBuildError, Z3BackendUnavailable, Z3LoweringError) as exc:
        print(f"xlsform proof failed: {exc}")
        return 1

    workbook_pairwise = json.loads(built.workbook_pairwise_report_path.read_text(encoding="utf-8"))
    backend_compare = json.loads(built.backend_compare_path.read_text(encoding="utf-8"))
    ir_lint = json.loads(built.ir_lint_path.read_text(encoding="utf-8"))
    z3_checks = json.loads(built.z3_checks_path.read_text(encoding="utf-8"))
    workbook_source_lint = json.loads((built.root_dir / "source_workbook.lint.json").read_text(encoding="utf-8"))
    reference_pairwise = (
        json.loads(built.reference_equivalence_report_path.read_text(encoding="utf-8"))
        if built.reference_equivalence_report_path is not None
        else None
    )

    print(f"wrote proof summary to {built.summary_path}")
    print(f"wrote imported IR to {built.imported_ir_path}")
    print(f"wrote import report to {built.import_report_path}")
    print(f"wrote workbook pairwise report to {built.workbook_pairwise_report_path}")
    print(f"wrote backend comparison report to {built.backend_compare_path}")
    print(f"wrote z3 checks report to {built.z3_checks_path}")
    if built.reference_equivalence_report_path is not None:
        print(f"wrote reference pairwise report to {built.reference_equivalence_report_path}")

    has_ir_lint_errors = any(item["level"] == "ERROR" for item in ir_lint.get("issues", []))
    has_source_lint_errors = any(item["level"] == "ERROR" for item in workbook_source_lint.get("issues", []))
    backend_ok = all(item.get("ok") for item in backend_compare.get("results", []))
    z3_ok = all(item.get("ok", False) for item in z3_checks.get("results", []))
    workbook_ok = workbook_pairwise.get("equivalent_on_case_suite", False)
    reference_ok = reference_pairwise is None or reference_pairwise.get("equivalent_on_case_suite", False)
    return 0 if all((not has_ir_lint_errors, not has_source_lint_errors, backend_ok, z3_ok, workbook_ok, reference_ok)) else 1


def _handle_import_dmn(base_ir_path: Path, dmn_path: Path, output_path: str | None) -> int:
    try:
        document = _load_document(base_ir_path)
        merged = import_dmn_decisions(document, str(dmn_path))
    except (CLIError, DMNImportError) as exc:
        print(f"dmn import failed: {exc}")
        return 1
    rendered = json.dumps(_document_to_dict(merged), indent=2, sort_keys=True)
    if output_path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
        print(f"wrote merged IR to {output_path}")
    else:
        print(rendered)
    return 0


def _handle_z3_summary(ir_path: Path) -> int:
    try:
        document = _load_document(ir_path)
    except CLIError as exc:
        print(f"z3 lowering unavailable: {exc}")
        return 1
    try:
        model = build_z3_model(document)
    except (Z3BackendUnavailable, Z3LoweringError) as exc:
        print(f"z3 lowering unavailable: {exc}")
        return 1

    print("z3 lowering succeeded")
    print(f"- variables: {len(model.variables)}")
    print(f"- variable missing flags: {len(model.variable_missing)}")
    print(f"- predicates: {len(model.predicates)}")
    print(f"- predicate missing flags: {len(model.predicate_missing)}")
    print(f"- outputs: {len(model.outputs)}")
    print(f"- rule hits: {len(model.rule_hits)}")
    print(f"- invariants: {len(model.invariants)}")
    print(f"- solver assertions: {len(model.solver.assertions())}")
    return 0


def _handle_z3_checks(ir_path: Path) -> int:
    try:
        document = _load_document(ir_path)
    except CLIError as exc:
        print(f"z3 analysis unavailable: {exc}")
        return 1
    try:
        report = analyze_document(document)
    except (Z3BackendUnavailable, Z3LoweringError) as exc:
        print(f"z3 analysis unavailable: {exc}")
        return 1

    rendered = build_z3_checks_log(guideline_id=document.metadata.guideline_id, report=report)
    print(json.dumps(rendered, indent=2, sort_keys=True))
    return 0


def _handle_z3_rule_patient(ir_path: Path, rule_id: str) -> int:
    try:
        document = _load_document(ir_path)
    except CLIError as exc:
        print(f"z3 patient generation unavailable: {exc}")
        return 1
    try:
        witness = generate_patient_for_rule(document, rule_id)
    except (Z3BackendUnavailable, Z3LoweringError) as exc:
        print(f"z3 patient generation unavailable: {exc}")
        return 1

    if witness is None:
        print(json.dumps({"rule_id": rule_id, "reachable": False}, indent=2, sort_keys=True))
        return 0

    print(
        json.dumps(
            {
                "rule_id": rule_id,
                "reachable": True,
                "witness": _clean(witness),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _handle_export_smt2(ir_path: Path, output_path: str | None) -> int:
    try:
        document = _load_document(ir_path)
    except CLIError as exc:
        print(f"smt2 export unavailable: {exc}")
        return 1
    try:
        text = export_smt2(document)
    except (Z3BackendUnavailable, Z3LoweringError) as exc:
        print(f"smt2 export unavailable: {exc}")
        return 1

    if output_path:
        written = write_smt2(document, output_path)
        print(f"wrote smt2 model to {written}")
    else:
        print(text)
    return 0


def _handle_compare_smt2(ir_path: Path, smt2_path: str, patient_path: str | None) -> int:
    try:
        document = _load_document(ir_path)
    except CLIError as exc:
        print(f"smt2 comparison failed: {exc}")
        return 1
    try:
        patient_cases = load_patient_cases(patient_path) if patient_path else None
        if patient_cases is None:
            raise ComparisonError("compare-smt2 requires an explicit patient case file")
        results = compare_smt2_file(document, smt2_path, patient_cases)
    except (ComparisonError, Z3BackendUnavailable, Z3LoweringError) as exc:
        print(f"smt2 comparison failed: {exc}")
        return 1

    print(json.dumps([_clean(item) for item in results], indent=2, sort_keys=True))
    return 0


def _handle_build_xlsform(ir_path: Path, output_dir: str) -> int:
    try:
        document = _load_document(ir_path)
    except CLIError as exc:
        print(f"xlsform build failed: {exc}")
        return 1
    try:
        built = build_xlsform(document)
        survey_path, choices_path, source_map_path = write_xlsform_csvs(built, output_dir)
    except XLSFormBuildError as exc:
        print(f"xlsform build failed: {exc}")
        return 1

    print(f"wrote survey sheet to {survey_path}")
    print(f"wrote choices sheet to {choices_path}")
    print(f"wrote source map to {source_map_path}")
    return 0


def _handle_build_cht(
    ir_path: Path,
    task_bindings_path: Path,
    output_dir: Path,
    include_reviewed_special_functions: bool,
    local_data_bindings_path: str | None,
    form_context: str,
) -> int:
    try:
        document = _load_document(ir_path)
        task_bindings = load_cht_task_bindings(task_bindings_path)
        local_data_registry = (
            load_cht_local_data_registry(local_data_bindings_path)
            if local_data_bindings_path is not None
            else None
        )
        built = build_xlsform(document)
        plan = build_cht_lowering_plan(
            document,
            built,
            task_bindings=task_bindings,
            local_data_registry=local_data_registry,
            form_context=form_context,
            special_function_target_cht_version=(
                task_bindings.target_cht_version if include_reviewed_special_functions else None
            ),
        )
        artifacts = write_cht_adapter_bundle(plan, output_dir)
    except (
        CLIError,
        XLSFormBuildError,
        CHTTaskLoweringError,
        CHTLocalDataLoweringError,
        ValueError,
    ) as exc:
        print(f"CHT build failed: {exc}")
        return 1

    print(f"wrote CHT bundle manifest to {artifacts.manifest_path}")
    if artifacts.tasks_js_path is not None:
        print(f"wrote executable CHT task rules to {artifacts.tasks_js_path}")
    if artifacts.form_survey_path is not None:
        print(f"wrote matching CHT XLSForm survey source to {artifacts.form_survey_path}")
    if artifacts.form_xform_path is not None:
        print(f"wrote executable CHT XForm to {artifacts.form_xform_path}")
    if artifacts.special_function_paths:
        print(f"wrote {len(artifacts.special_function_paths)} reviewed special-function files")
    return 0


def _handle_quality_check(ir_path: Path, output_dir: Path, patient_path: str | None) -> int:
    try:
        document = _load_document(ir_path)
    except CLIError as exc:
        print(f"quality check failed: {exc}")
        return 1
    try:
        patient_cases = load_patient_cases(patient_path) if patient_path else None
        artifacts = run_quality_checks(
            document,
            output_dir=output_dir,
            source_ir_path=ir_path,
            patient_cases=patient_cases,
        )
    except (XLSFormBuildError, ComparisonError, Z3BackendUnavailable, Z3LoweringError) as exc:
        print(f"quality check failed: {exc}")
        return 1

    print(json.dumps(_clean(artifacts), indent=2, sort_keys=True))
    return 0


def _handle_lint_xlsform(survey_path: Path, choices_path: Path, output_path: str | None) -> int:
    report = lint_xlsform_artifacts(survey_path, choices_path)
    rendered = render_stage_lint_report(report)
    if output_path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"wrote XLSForm lint report to {output}")
    else:
        print(rendered, end="")
    return 0 if report.ok else 1


def _handle_build_mermaid(ir_path: Path, output_path: str | None, direction: str, font_size: int) -> int:
    try:
        document = _load_document(ir_path)
    except CLIError as exc:
        print(f"mermaid build failed: {exc}")
        return 1
    artifact = build_mermaid_artifact(document, options=MermaidOptions(direction=direction, font_size_px=font_size))
    if output_path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(artifact.text, encoding="utf-8")
        source_map_path = output.with_suffix(output.suffix + ".source-map.json")
        source_map_path.write_text(
            json.dumps({"node_sources": artifact.node_sources}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"wrote mermaid diagram to {output_path}")
        print(f"wrote mermaid source map to {source_map_path}")
    else:
        print(artifact.text)
    return 0


def _handle_lint_mermaid(ir_path: Path, candidate_path: str | None, output_path: str | None) -> int:
    try:
        document = _load_document(ir_path)
    except CLIError as exc:
        print(f"mermaid lint failed: {exc}")
        return 1
    candidate_text = None
    if candidate_path:
        try:
            candidate_text = Path(candidate_path).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"mermaid lint failed: could not read candidate Mermaid '{candidate_path}': {exc}")
            return 1
    report = lint_mermaid_artifact(document, candidate_text=candidate_text)
    rendered = render_stage_lint_report(report)
    if output_path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"wrote Mermaid lint report to {output}")
    else:
        print(rendered, end="")
    return 0 if report.ok else 1


def _handle_compare(ir_path: Path, dmn_path: str | None, patient_path: str | None) -> int:
    try:
        document = _load_document(ir_path)
    except CLIError as exc:
        print(f"comparison failed: {exc}")
        return 1
    try:
        patient_cases = load_patient_cases(patient_path) if patient_path else None
        results = compare_backends(document, dmn_path=dmn_path, patient_cases=patient_cases)
    except (ComparisonError, XLSFormBuildError, Z3BackendUnavailable, Z3LoweringError, DMNImportError) as exc:
        print(f"comparison failed: {exc}")
        return 1

    print(
        json.dumps(
            build_comparison_log(
                guideline_id=document.metadata.guideline_id,
                results=results,
                source_artifacts={
                    "ir_path": str(ir_path),
                    "dmn_path": dmn_path,
                    "patient_path": patient_path,
                },
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _handle_build_equivalence_report(
    baseline_ir_path: Path,
    candidate_ir_path: Path,
    patient_path: Path,
    output_dir: Path,
) -> int:
    try:
        baseline_document = _load_document(baseline_ir_path)
        candidate_document = _load_document(candidate_ir_path)
        patient_cases = load_patient_cases(str(patient_path))
    except (CLIError, ComparisonError) as exc:
        print(f"equivalence build failed: {exc}")
        return 1
    built = build_case_suite_equivalence_report(
        baseline_document=baseline_document,
        candidate_document=candidate_document,
        patient_cases=patient_cases,
        output_dir=output_dir,
        baseline_label=baseline_document.metadata.guideline_id,
        candidate_label=candidate_document.metadata.guideline_id,
    )
    print(f"wrote equivalence report to {built.report_path}")
    print(f"wrote equivalence summary to {built.summary_path}")
    report = json.loads(built.report_path.read_text(encoding="utf-8"))
    return 0 if report.get("equivalent_on_case_suite") else 1


def _handle_lint_smt2(ir_path: Path, candidate_path: str | None, output_path: str | None) -> int:
    try:
        document = _load_document(ir_path)
    except CLIError as exc:
        print(f"smt2 lint failed: {exc}")
        return 1
    candidate_text = None
    if candidate_path:
        try:
            candidate_text = Path(candidate_path).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"smt2 lint failed: could not read candidate SMT-LIB '{candidate_path}': {exc}")
            return 1
    report = lint_smt_artifact(document, candidate_text=candidate_text)
    rendered = render_stage_lint_report(report)
    if output_path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"wrote SMT lint report to {output}")
    else:
        print(rendered, end="")
    return 0 if report.ok else 1


def _handle_create_bundle(
    ir_path: Path,
    dmn_path: Path,
    bundle_root: str,
    patient_path: str | None,
    source_label: str | None,
) -> int:
    try:
        document = _load_document(ir_path)
    except CLIError as exc:
        print(f"bundle creation failed: {exc}")
        return 1
    try:
        built = create_bundle(
            base_document=document,
            base_ir_path=ir_path,
            dmn_path=dmn_path,
            bundle_root=Path(bundle_root),
            patient_cases_path=Path(patient_path) if patient_path else None,
            source_label=source_label,
        )
    except (
        BundleBuildError,
        ComparisonError,
        DMNImportError,
        XLSFormBuildError,
        Z3BackendUnavailable,
        Z3LoweringError,
    ) as exc:
        print(f"bundle creation failed: {exc}")
        return 1

    print(f"created bundle at {built.bundle_dir}")
    print(f"wrote metadata to {built.metadata_path}")
    print(f"wrote bundle README to {built.readme_path}")
    if built.explicit_compare_path is not None:
        print(f"wrote explicit comparison report to {built.explicit_compare_path}")
    print(f"wrote Z3-derived comparison report to {built.derived_compare_path}")
    print(f"wrote derived comparison cases to {built.derived_cases_path}")
    return 0


def _handle_build_change_review(
    memo_path: Path,
    baseline_ir_path: Path,
    updated_ir_path: Path,
    review_root: Path,
    patient_path: str | None,
    baseline_dmn_path: str | None,
    updated_dmn_path: str | None,
) -> int:
    try:
        memo = load_change_memo(memo_path)
        baseline_document = _load_document(baseline_ir_path)
        updated_document = _load_document(updated_ir_path)
    except (CLIError, ChangeReviewBuildError) as exc:
        print(f"change-review build failed: {exc}")
        return 1
    try:
        built = create_change_review_package(
            memo=memo,
            baseline_document=baseline_document,
            updated_document=updated_document,
            review_root=review_root,
            baseline_ir_path=baseline_ir_path,
            updated_ir_path=updated_ir_path,
            patient_cases_path=Path(patient_path) if patient_path else None,
            baseline_dmn_path=Path(baseline_dmn_path) if baseline_dmn_path else None,
            updated_dmn_path=Path(updated_dmn_path) if updated_dmn_path else None,
        )
    except ChangeReviewBuildError as exc:
        print(f"change-review build failed: {exc}")
        return 1

    print(f"created change review at {built.review_dir}")
    print(f"wrote metadata to {built.metadata_path}")
    print(f"wrote review README to {built.readme_path}")
    print(f"wrote change summary to {built.summary_path}")
    print(f"wrote semantic diff to {built.semantic_diff_path}")
    print(f"wrote impact map to {built.impact_map_path}")
    print(f"wrote XLSForm delta to {built.xlsform_diff_path}")
    print(f"wrote workflow burden to {built.workflow_burden_path}")
    if built.case_delta_path is not None:
        print(f"wrote case delta to {built.case_delta_path}")
    return 0


def _load_document(path: Path) -> ClinicalIRDocument:
    data = _load_json_file(path, "Clinical IR document")
    if not isinstance(data, dict):
        raise CLIError(f"Clinical IR document '{path}' must contain a JSON object at the top level")
    try:
        return ClinicalIRDocument.from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise CLIError(f"Clinical IR document '{path}' is invalid: {exc}") from exc


def _load_json_file(path: Path, label: str) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CLIError(f"{label} '{path}' not found") from exc
    except OSError as exc:
        raise CLIError(f"could not read {label} '{path}': {exc}") from exc
    try:
        return json.loads(text)
    except JSONDecodeError as exc:
        raise CLIError(f"{label} '{path}' is not valid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}") from exc


def _document_to_dict(document: ClinicalIRDocument) -> dict[str, object]:
    return _clean(document)  # type: ignore[return-value]


def _clean(value: object) -> object:
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _clean(getattr(value, key))
            for key in value.__dataclass_fields__
        }
    return value


if __name__ == "__main__":
    raise SystemExit(main())
