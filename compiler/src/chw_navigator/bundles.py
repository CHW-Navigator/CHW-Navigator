from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .clinical_ir import ClinicalIRDocument
from .compare import (
    ComparisonCase,
    build_comparison_log,
    build_z3_checks_log,
    compare_backends,
    load_patient_cases,
)
from .dmn import import_dmn_decisions
from .evidence_utils import allocate_timestamped_dir, compiler_metadata, describe_file, portable_relative_path
from .mermaid_backend import build_mermaid_artifact
from .staged_lint import (
    lint_ir_document,
    lint_mermaid_artifact,
    lint_smt_artifact,
    lint_xlsform_artifacts,
    preflight_source_artifact,
    render_stage_lint_report,
)
from .validator import validate_document
from .xlsform_backend import build_xlsform, write_xlsform_csvs
from .z3_backend import analyze_document, export_smt2


class BundleBuildError(Exception):
    """Raised when a bundle cannot be created or validated."""


@dataclass(slots=True)
class BundleArtifacts:
    bundle_dir: Path
    metadata_path: Path
    hash_manifest_path: Path
    readme_path: Path
    explicit_compare_path: Path | None
    derived_compare_path: Path
    derived_cases_path: Path


def create_bundle(
    *,
    base_document: ClinicalIRDocument,
    base_ir_path: Path,
    dmn_path: Path,
    bundle_root: Path,
    patient_cases_path: Path | None = None,
    source_label: str | None = None,
) -> BundleArtifacts:
    validation_errors = validate_document(base_document)
    if validation_errors:
        rendered = "; ".join(f"{error.path}: {error.message}" for error in validation_errors)
        raise BundleBuildError(f"base Clinical IR failed validation: {rendered}")

    if not dmn_path.exists():
        raise BundleBuildError(f"DMN input does not exist: {dmn_path}")

    if patient_cases_path is not None and not patient_cases_path.exists():
        raise BundleBuildError(f"patient case file does not exist: {patient_cases_path}")

    label = source_label or dmn_path.stem
    bundle_root.mkdir(parents=True, exist_ok=True)
    bundle_dir = _allocate_bundle_dir(bundle_root, label)
    _create_bundle_scaffold(bundle_dir)
    try:
        merged_document = import_dmn_decisions(base_document, str(dmn_path))
        merged_validation_errors = validate_document(merged_document)
        if merged_validation_errors:
            rendered = "; ".join(f"{error.path}: {error.message}" for error in merged_validation_errors)
            raise BundleBuildError(f"DMN-imported Clinical IR failed validation: {rendered}")

        explicit_cases = load_patient_cases(str(patient_cases_path)) if patient_cases_path else None
        derived_results = compare_backends(merged_document, dmn_path=str(dmn_path))
        derived_cases = [_case_from_result(item) for item in derived_results]

        if not derived_cases:
            raise BundleBuildError("could not derive any comparison cases from Z3 witnesses")

        explicit_results = (
            compare_backends(merged_document, dmn_path=str(dmn_path), patient_cases=explicit_cases)
            if explicit_cases is not None
            else None
        )
        z3_report = analyze_document(merged_document)
        xlsform = build_xlsform(merged_document)
        mermaid = build_mermaid_artifact(merged_document)
        smt2_text = export_smt2(merged_document)

        input_dir = bundle_dir / "inputs"
        output_dir = bundle_dir / "outputs"
        tests_dir = bundle_dir / "tests"
        mutation_dir = bundle_dir / "mutations"

        copied_base_ir_path = input_dir / "base.ir.json"
        copied_dmn_path = input_dir / "source.dmn"
        copied_cases_path = input_dir / "explicit.cases.json" if patient_cases_path else None
        shutil.copy2(base_ir_path, copied_base_ir_path)
        shutil.copy2(dmn_path, copied_dmn_path)
        if patient_cases_path and copied_cases_path is not None:
            shutil.copy2(patient_cases_path, copied_cases_path)

        input_lint_dir = input_dir / "lint"
        input_lint_dir.mkdir(parents=True, exist_ok=True)
        base_ir_lint_path = input_lint_dir / "base.ir.lint.json"
        base_ir_lint_path.write_text(
            render_stage_lint_report(lint_ir_document(base_document, source_path=str(base_ir_path))),
            encoding="utf-8",
        )
        dmn_lint_path = input_lint_dir / "source.dmn.lint.json"
        dmn_lint_path.write_text(
            render_stage_lint_report(preflight_source_artifact("dmn", copied_dmn_path)),
            encoding="utf-8",
        )
        explicit_cases_lint_path: Path | None = None
        if copied_cases_path is not None:
            explicit_cases_lint_path = input_lint_dir / "explicit.cases.lint.json"
            explicit_cases_lint_path.write_text(
                render_stage_lint_report(preflight_source_artifact("patient_cases", copied_cases_path)),
                encoding="utf-8",
            )

        merged_ir_path = output_dir / "merged.ir.json"
        merged_ir_path.write_text(json.dumps(_clean(merged_document), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        output_lint_dir = output_dir / "lint"
        output_lint_dir.mkdir(parents=True, exist_ok=True)
        merged_ir_lint_path = output_lint_dir / "merged.ir.lint.json"
        merged_ir_lint_path.write_text(
            render_stage_lint_report(lint_ir_document(merged_document, source_path="outputs/merged.ir.json")),
            encoding="utf-8",
        )

        xlsform_dir = output_dir / "xlsform"
        survey_path_raw, choices_path_raw, source_map_path_raw = write_xlsform_csvs(xlsform, xlsform_dir)
        survey_path = Path(survey_path_raw)
        choices_path = Path(choices_path_raw)
        source_map_path = Path(source_map_path_raw)
        xlsform_lint_path = xlsform_dir / "lint.json"
        xlsform_lint_path.write_text(
            render_stage_lint_report(lint_xlsform_artifacts(survey_path, choices_path)),
            encoding="utf-8",
        )

        mermaid_dir = output_dir / "mermaid"
        mermaid_path = mermaid_dir / f"{label}.mmd"
        mermaid_dir.mkdir(parents=True, exist_ok=True)
        mermaid_path.write_text(mermaid.text, encoding="utf-8")
        mermaid_source_map_path = mermaid_dir / f"{label}.mmd.source-map.json"
        mermaid_source_map_path.write_text(
            json.dumps({"node_sources": mermaid.node_sources}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        mermaid_lint_path = mermaid_dir / "lint.json"
        mermaid_lint_path.write_text(
            render_stage_lint_report(lint_mermaid_artifact(merged_document, candidate_text=mermaid.text)),
            encoding="utf-8",
        )

        z3_dir = output_dir / "z3"
        z3_dir.mkdir(parents=True, exist_ok=True)
        smt2_path = z3_dir / f"{label}.smt2"
        smt2_path.write_text(smt2_text, encoding="utf-8")
        smt2_lint_path = z3_dir / "smt2.lint.json"
        smt2_lint_path.write_text(
            render_stage_lint_report(lint_smt_artifact(merged_document, candidate_text=smt2_text)),
            encoding="utf-8",
        )
        z3_checks_path = z3_dir / "z3-checks.json"
        z3_checks_path.write_text(
            json.dumps(
                build_z3_checks_log(
                    guideline_id=merged_document.metadata.guideline_id,
                    report=z3_report,
                    source_artifacts={
                        "ir_path": "outputs/merged.ir.json",
                        "dmn_path": "inputs/source.dmn",
                    },
                ),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        derived_cases_path = z3_dir / "derived.cases.json"
        derived_cases_path.write_text(
            json.dumps({"cases": [_clean(case) for case in derived_cases]}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        good_tests_dir = tests_dir / "good"
        good_tests_dir.mkdir(parents=True, exist_ok=True)
        derived_compare_path = good_tests_dir / "z3-derived.compare.json"
        derived_compare_path.write_text(
            json.dumps(
                build_comparison_log(
                    guideline_id=merged_document.metadata.guideline_id,
                    results=derived_results,
                    source_artifacts={
                        "ir_path": "outputs/merged.ir.json",
                        "dmn_path": "inputs/source.dmn",
                        "patient_path": "outputs/z3/derived.cases.json",
                    },
                ),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        explicit_compare_path: Path | None = None
        if explicit_results is not None:
            explicit_compare_path = good_tests_dir / "explicit.compare.json"
            explicit_compare_path.write_text(
                json.dumps(
                    build_comparison_log(
                        guideline_id=merged_document.metadata.guideline_id,
                        results=explicit_results,
                        source_artifacts={
                            "ir_path": "outputs/merged.ir.json",
                            "dmn_path": "inputs/source.dmn",
                            "patient_path": "inputs/explicit.cases.json",
                        },
                    ),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

        _write_mutation_manifest(mutation_dir, label)
        metadata = _build_metadata(
            bundle_dir=bundle_dir,
            label=label,
            source_label=source_label,
            base_ir_path=base_ir_path,
            dmn_path=dmn_path,
            patient_cases_path=patient_cases_path,
            copied_base_ir_path=copied_base_ir_path,
            copied_dmn_path=copied_dmn_path,
            copied_cases_path=copied_cases_path,
            merged_ir_path=merged_ir_path,
            survey_path=survey_path,
            choices_path=choices_path,
            source_map_path=source_map_path,
            mermaid_path=mermaid_path,
            mermaid_source_map_path=mermaid_source_map_path,
            smt2_path=smt2_path,
            z3_checks_path=z3_checks_path,
            derived_cases_path=derived_cases_path,
            explicit_compare_path=explicit_compare_path,
            derived_compare_path=derived_compare_path,
            hash_manifest_path=bundle_dir / "artifact_hashes.json",
            base_ir_lint_path=base_ir_lint_path,
            dmn_lint_path=dmn_lint_path,
            explicit_cases_lint_path=explicit_cases_lint_path,
            merged_ir_lint_path=merged_ir_lint_path,
            xlsform_lint_path=xlsform_lint_path,
            mermaid_lint_path=mermaid_lint_path,
            smt2_lint_path=smt2_lint_path,
        )
        metadata_path = bundle_dir / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        key_hashes = _build_bundle_key_hashes(
            bundle_dir,
            copied_base_ir_path=copied_base_ir_path,
            copied_dmn_path=copied_dmn_path,
            copied_cases_path=copied_cases_path,
            merged_ir_path=merged_ir_path,
            mermaid_path=mermaid_path,
            smt2_path=smt2_path,
            derived_compare_path=derived_compare_path,
            explicit_compare_path=explicit_compare_path,
        )
        metadata["key_artifact_hashes"] = key_hashes
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        readme_path = bundle_dir / "README.md"
        readme_path.write_text(_render_bundle_readme(metadata), encoding="utf-8")
        hash_manifest_path = bundle_dir / "artifact_hashes.json"
        hash_manifest_path.write_text(
            json.dumps(
                _build_hash_manifest(
                    bundle_dir,
                    metadata_path=metadata_path,
                    readme_path=readme_path,
                ),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        return BundleArtifacts(
            bundle_dir=bundle_dir,
            metadata_path=metadata_path,
            hash_manifest_path=hash_manifest_path,
            readme_path=readme_path,
            explicit_compare_path=explicit_compare_path,
            derived_compare_path=derived_compare_path,
            derived_cases_path=derived_cases_path,
        )
    except Exception:
        shutil.rmtree(bundle_dir, ignore_errors=True)
        raise


def _allocate_bundle_dir(bundle_root: Path, label: str) -> Path:
    return allocate_timestamped_dir(bundle_root, label, fallback_slug="bundle")


def _create_bundle_scaffold(bundle_dir: Path) -> None:
    for relative in (
        "inputs",
        "inputs/lint",
        "outputs",
        "outputs/lint",
        "outputs/xlsform",
        "outputs/mermaid",
        "outputs/z3",
        "tests",
        "tests/good",
        "tests/mutations",
        "mutations",
        "mutations/dmn",
        "mutations/ir",
        "mutations/xlsform",
        "mutations/mermaid",
        "mutations/smt2",
    ):
        (bundle_dir / relative).mkdir(parents=True, exist_ok=True)


def _case_from_result(result: Any) -> ComparisonCase:
    values = dict(getattr(result, "inputs"))
    missing = set(getattr(result, "missing", []))
    return ComparisonCase(
        name=str(getattr(result, "name")),
        values=values,
        missing=missing,
        category=getattr(result, "category", None),
        tags=list(getattr(result, "tags", [])),
    )


def _write_mutation_manifest(mutation_dir: Path, label: str) -> None:
    mutation_manifest = {
        "label": label,
        "expected_candidates": {
            "dmn": "mutations/dmn/candidate.dmn",
            "ir": "mutations/ir/candidate.ir.json",
            "xlsform_survey": "mutations/xlsform/survey.csv",
            "xlsform_choices": "mutations/xlsform/choices.csv",
            "mermaid": "mutations/mermaid/candidate.mmd",
            "smt2": "mutations/smt2/candidate.smt2",
        },
        "notes": [
            "Copy one generated artifact into the matching mutation folder before editing it.",
            "Mutation tests should demonstrate that semantic drift is detected rather than silently accepted.",
        ],
    }
    (mutation_dir / "manifest.json").write_text(
        json.dumps(mutation_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (mutation_dir / "README.md").write_text(
        "\n".join(
            [
                "# Mutation Workspace",
                "",
                "Use this folder to keep deliberately altered candidate artifacts beside the canonical outputs for this bundle.",
                "",
                "Recommended filenames:",
                "",
                "- `dmn/candidate.dmn`",
                "- `ir/candidate.ir.json`",
                "- `xlsform/survey.csv` and `xlsform/choices.csv`",
                "- `mermaid/candidate.mmd`",
                "- `smt2/candidate.smt2`",
                "",
                "Mutation tests should fail the relevant comparison step when the candidate no longer matches the canonical logic.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _build_metadata(**kwargs: Any) -> dict[str, Any]:
    return {
        "bundle_id": kwargs["bundle_dir"].name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "compiler": compiler_metadata(),
        "source": {
            "label": kwargs["label"],
            "source_label": kwargs["source_label"],
            "base_ir_path": str(kwargs["base_ir_path"].resolve()),
            "dmn_path": str(kwargs["dmn_path"].resolve()),
            "patient_cases_path": str(kwargs["patient_cases_path"].resolve()) if kwargs["patient_cases_path"] else None,
        },
        "copied_inputs": {
            "base_ir": _portable_relative_path(kwargs["copied_base_ir_path"], kwargs["bundle_dir"]),
            "dmn": _portable_relative_path(kwargs["copied_dmn_path"], kwargs["bundle_dir"]),
            "patient_cases": (
                _portable_relative_path(kwargs["copied_cases_path"], kwargs["bundle_dir"])
                if kwargs["copied_cases_path"] is not None
                else None
            ),
        },
        "lint_reports": {
            "base_ir": _portable_relative_path(kwargs["base_ir_lint_path"], kwargs["bundle_dir"]),
            "dmn": _portable_relative_path(kwargs["dmn_lint_path"], kwargs["bundle_dir"]),
            "patient_cases": (
                _portable_relative_path(kwargs["explicit_cases_lint_path"], kwargs["bundle_dir"])
                if kwargs["explicit_cases_lint_path"] is not None
                else None
            ),
            "merged_ir": _portable_relative_path(kwargs["merged_ir_lint_path"], kwargs["bundle_dir"]),
            "xlsform": _portable_relative_path(kwargs["xlsform_lint_path"], kwargs["bundle_dir"]),
            "mermaid": _portable_relative_path(kwargs["mermaid_lint_path"], kwargs["bundle_dir"]),
            "smt2": _portable_relative_path(kwargs["smt2_lint_path"], kwargs["bundle_dir"]),
        },
        "outputs": {
            "merged_ir": _portable_relative_path(kwargs["merged_ir_path"], kwargs["bundle_dir"]),
            "xlsform_survey": _portable_relative_path(kwargs["survey_path"], kwargs["bundle_dir"]),
            "xlsform_choices": _portable_relative_path(kwargs["choices_path"], kwargs["bundle_dir"]),
            "xlsform_source_map": _portable_relative_path(kwargs["source_map_path"], kwargs["bundle_dir"]),
            "mermaid": _portable_relative_path(kwargs["mermaid_path"], kwargs["bundle_dir"]),
            "mermaid_source_map": _portable_relative_path(kwargs["mermaid_source_map_path"], kwargs["bundle_dir"]),
            "smt2": _portable_relative_path(kwargs["smt2_path"], kwargs["bundle_dir"]),
            "z3_checks": _portable_relative_path(kwargs["z3_checks_path"], kwargs["bundle_dir"]),
            "derived_cases": _portable_relative_path(kwargs["derived_cases_path"], kwargs["bundle_dir"]),
        },
        "tests": {
            "explicit_compare": (
                _portable_relative_path(kwargs["explicit_compare_path"], kwargs["bundle_dir"])
                if kwargs["explicit_compare_path"] is not None
                else None
            ),
            "derived_compare": _portable_relative_path(kwargs["derived_compare_path"], kwargs["bundle_dir"]),
        },
        "artifact_hash_manifest": _portable_relative_path(kwargs["hash_manifest_path"], kwargs["bundle_dir"]),
    }


def _render_bundle_readme(metadata: dict[str, Any]) -> str:
    source = metadata["source"]
    copied_inputs = metadata["copied_inputs"]
    lint_reports = metadata["lint_reports"]
    outputs = metadata["outputs"]
    tests = metadata["tests"]
    compiler = metadata["compiler"]
    key_hashes = metadata.get("key_artifact_hashes", {})
    lines = [
        f"# Bundle `{metadata['bundle_id']}`",
        "",
        "This bundle captures one DMN intake, its copied source inputs, the generated canonical artifacts, and the baseline comparison reports used to confirm semantic agreement.",
        "",
        "## Provenance",
        "",
        f"- Created: `{metadata['created_at']}`",
        f"- Compiler version: `{compiler['version']}`",
        f"- Python: `{compiler['python']}`",
        f"- Platform: `{compiler['platform']}`",
        f"- Git commit: `{compiler['git_commit'] or 'unknown'}`",
        f"- Source label: `{source['source_label'] or source['label']}`",
        f"- Original base IR: `{source['base_ir_path']}`",
        f"- Original DMN: `{source['dmn_path']}`",
        f"- Original patient cases: `{source['patient_cases_path'] or 'none provided'}`",
        "",
        "## Bundle Layout",
        "",
        f"- Inputs: `{copied_inputs['base_ir']}`, `{copied_inputs['dmn']}`"
        + (f", `{copied_inputs['patient_cases']}`" if copied_inputs["patient_cases"] else ""),
        f"- Lint reports: `{lint_reports['base_ir']}`, `{lint_reports['dmn']}`, `{lint_reports['merged_ir']}`, `{lint_reports['xlsform']}`, `{lint_reports['mermaid']}`, `{lint_reports['smt2']}`"
        + (f", `{lint_reports['patient_cases']}`" if lint_reports["patient_cases"] else ""),
        f"- Canonical IR: `{outputs['merged_ir']}`",
        f"- XLSForm: `{outputs['xlsform_survey']}`, `{outputs['xlsform_choices']}`, `{outputs['xlsform_source_map']}`",
        f"- Mermaid: `{outputs['mermaid']}`, `{outputs['mermaid_source_map']}`",
        f"- Z3: `{outputs['smt2']}`, `{outputs['z3_checks']}`, `{outputs['derived_cases']}`",
        f"- Good-path tests: `{tests['derived_compare']}`"
        + (f", `{tests['explicit_compare']}`" if tests["explicit_compare"] else ""),
        f"- Artifact hash manifest: `{metadata['artifact_hash_manifest']}`",
        "- Mutation workspace: `mutations/` with expected candidate filenames documented in `mutations/manifest.json`",
        "",
        "## Key Evidence Hashes",
        "",
    ]
    if isinstance(key_hashes, dict) and key_hashes:
        for label, entry in key_hashes.items():
            if not isinstance(entry, dict):
                continue
            lines.append(
                f"- `{label}`: `{entry.get('path')}` sha256 `{str(entry.get('sha256', ''))[:16]}...` ({entry.get('size_bytes')} bytes)"
            )
        lines.extend(
            [
                "",
                "The full hash list is preserved in `artifact_hashes.json` for exact verification.",
                "",
            ]
        )
    else:
        lines.extend(["- No key hashes recorded", ""])
    lines.extend(
        [
        "## Expected Workflow",
        "",
        "1. Copy a new DMN and base IR into a fresh bundle by rerunning the bundle command. Do not overwrite older bundles.",
        "2. Review the copied inputs and generated outputs in this folder.",
        "3. Add deliberate drift candidates under `mutations/` when you want to prove that mismatch detection still works.",
        "4. Keep any new patient suites or reviewer notes in this bundle so the audit trail stays attached to the exact compiler version and source snapshot.",
        "",
        ]
    )
    return "\n".join(lines)


def _build_hash_manifest(bundle_dir: Path, *, metadata_path: Path, readme_path: Path) -> dict[str, Any]:
    files: list[Path] = []
    for file_path in bundle_dir.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.name == "artifact_hashes.json":
            continue
        files.append(file_path)
    files.sort(key=lambda path: portable_relative_path(path, bundle_dir))
    return {
        "algorithm": "sha256",
        "files": [describe_file(path, bundle_dir) for path in files],
        "notes": {
            "metadata_path": portable_relative_path(metadata_path, bundle_dir),
            "readme_path": portable_relative_path(readme_path, bundle_dir),
        },
    }


def _build_bundle_key_hashes(
    bundle_dir: Path,
    *,
    copied_base_ir_path: Path,
    copied_dmn_path: Path,
    copied_cases_path: Path | None,
    merged_ir_path: Path,
    mermaid_path: Path,
    smt2_path: Path,
    derived_compare_path: Path,
    explicit_compare_path: Path | None,
) -> dict[str, Any]:
    items = {
        "base_ir": copied_base_ir_path,
        "dmn": copied_dmn_path,
        "merged_ir": merged_ir_path,
        "mermaid": mermaid_path,
        "smt2": smt2_path,
        "derived_compare": derived_compare_path,
    }
    if copied_cases_path is not None:
        items["patient_cases"] = copied_cases_path
    if explicit_compare_path is not None:
        items["explicit_compare"] = explicit_compare_path
    return {label: describe_file(path, bundle_dir) for label, path in items.items()}


def _portable_relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _clean(value: object) -> object:
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, set):
        return sorted(_clean(item) for item in value)
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _clean(getattr(value, key))
            for key in value.__dataclass_fields__
        }
    return value
