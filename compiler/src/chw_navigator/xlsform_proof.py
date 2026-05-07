from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .clinical_ir import ClinicalIRDocument
from .compare import (
    ComparisonCase,
    build_comparison_log,
    build_z3_checks_log,
    compare_backends,
    compare_document_pair,
    compare_workbook_pair,
    derive_comparison_cases,
)
from .evidence_utils import compiler_metadata
from .staged_lint import lint_ir_document, lint_xlsform_artifacts
from .xlsform_import import import_xlsform_files_detailed
from .z3_backend import analyze_document


@dataclass(slots=True)
class XLSFormProofArtifacts:
    root_dir: Path
    imported_ir_path: Path
    import_report_path: Path
    ir_lint_path: Path
    workbook_pairwise_report_path: Path
    backend_compare_path: Path
    z3_checks_path: Path
    summary_path: Path
    reference_equivalence_report_path: Path | None = None
    reference_equivalence_summary_path: Path | None = None


def build_xlsform_roundtrip_proof(
    *,
    survey_path: str | Path,
    choices_path: str | Path,
    output_dir: str | Path,
    guideline_id: str | None = None,
    reference_document: ClinicalIRDocument | None = None,
    patient_cases: list[ComparisonCase] | None = None,
) -> XLSFormProofArtifacts:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    imported = import_xlsform_files_detailed(
        str(survey_path),
        str(choices_path),
        guideline_id=guideline_id,
    )
    cases = patient_cases or derive_comparison_cases(imported.document)

    imported_ir_path = target_dir / "imported.ir.json"
    imported_ir_path.write_text(json.dumps(_clean(imported.document), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    import_report_path = target_dir / "import_report.json"
    import_report_path.write_text(json.dumps(_clean(imported.report), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    ir_lint = lint_ir_document(imported.document, source_path=str(imported_ir_path))
    ir_lint_path = target_dir / "imported.ir.lint.json"
    ir_lint_path.write_text(json.dumps(_clean(ir_lint), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    workbook_pairwise = compare_workbook_pair(
        imported.document,
        imported.workbook,
        cases,
        label="original_workbook",
    )
    workbook_pairwise = _normalize_workbook_pairwise_results(workbook_pairwise, imported.workbook)
    workbook_pairwise_report = _build_pairwise_report(
        report_type="xlsform_roundtrip_workbook_pairwise",
        guideline_id=imported.document.metadata.guideline_id,
        label="original_workbook",
        results=workbook_pairwise,
        source_artifacts={
            "survey_path": str(Path(survey_path)),
            "choices_path": str(Path(choices_path)),
        },
    )
    workbook_pairwise_report_path = target_dir / "workbook_pairwise.compare.json"
    workbook_pairwise_report_path.write_text(
        json.dumps(workbook_pairwise_report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    backend_results = compare_backends(imported.document, patient_cases=cases)
    backend_compare_path = target_dir / "backend_compare.json"
    backend_compare_path.write_text(
        json.dumps(
            build_comparison_log(
                guideline_id=imported.document.metadata.guideline_id,
                results=backend_results,
                compiler_version=compiler_metadata()["version"],
                source_artifacts={
                    "survey_path": str(Path(survey_path)),
                    "choices_path": str(Path(choices_path)),
                    "imported_ir_path": str(imported_ir_path),
                },
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    z3_report = analyze_document(imported.document)
    z3_checks_path = target_dir / "z3_checks.json"
    z3_checks_path.write_text(
        json.dumps(
            build_z3_checks_log(
                guideline_id=imported.document.metadata.guideline_id,
                report=z3_report,
                compiler_version=compiler_metadata()["version"],
                source_artifacts={
                    "survey_path": str(Path(survey_path)),
                    "choices_path": str(Path(choices_path)),
                    "imported_ir_path": str(imported_ir_path),
                },
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    reference_equivalence_report_path: Path | None = None
    reference_equivalence_summary_path: Path | None = None
    reference_summary_lines: list[str] = []
    if reference_document is not None:
        pairwise = compare_document_pair(reference_document, imported.document, cases, label="imported_xlsform")
        report = _build_pairwise_report(
            report_type="xlsform_roundtrip_reference_pairwise",
            guideline_id=reference_document.metadata.guideline_id,
            label="imported_xlsform",
            results=pairwise,
            source_artifacts={
                "survey_path": str(Path(survey_path)),
                "choices_path": str(Path(choices_path)),
                "imported_ir_path": str(imported_ir_path),
            },
        )
        reference_equivalence_report_path = target_dir / "reference_pairwise.compare.json"
        reference_equivalence_report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        reference_equivalence_summary_path = target_dir / "reference_pairwise.summary.md"
        reference_summary_lines = [
            "## Reference IR Pairwise Check",
            "",
            f"- Equivalent on supplied case suite: `{str(report['equivalent_on_case_suite']).lower()}`",
            f"- Changed cases: `{report['changed_case_count']}`",
            "",
        ]
        reference_equivalence_summary_path.write_text("\n".join(reference_summary_lines), encoding="utf-8")

    xlsform_lint = lint_xlsform_artifacts(str(survey_path), str(choices_path))
    xlsform_lint_path = target_dir / "source_workbook.lint.json"
    xlsform_lint_path.write_text(json.dumps(_clean(xlsform_lint), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary_path = target_dir / "proof_summary.md"
    summary_lines = [
        "# XLSForm Round-Trip Proof",
        "",
        f"- Guideline id: `{imported.document.metadata.guideline_id}`",
        f"- Case count: `{len(cases)}`",
        f"- Workbook pairwise mismatching cases: `{sum(1 for item in workbook_pairwise if not item.ok)}`",
        f"- Backend comparison mismatching cases: `{sum(1 for item in backend_results if not item.ok)}`",
        f"- IR lint errors: `{sum(1 for item in ir_lint.issues if item.level == 'ERROR')}`",
        f"- Source workbook lint errors: `{sum(1 for item in xlsform_lint.issues if item.level == 'ERROR')}`",
        "",
        "Artifacts:",
        f"- Imported IR: `{imported_ir_path.name}`",
        f"- Import report: `{import_report_path.name}`",
        f"- Workbook pairwise report: `{workbook_pairwise_report_path.name}`",
        f"- Backend comparison report: `{backend_compare_path.name}`",
        f"- Z3 checks: `{z3_checks_path.name}`",
    ]
    if reference_document is not None and reference_equivalence_report_path is not None:
        summary_lines.extend(
            [
                f"- Reference pairwise report: `{reference_equivalence_report_path.name}`",
            ]
        )
    summary_lines.extend(reference_summary_lines)
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    return XLSFormProofArtifacts(
        root_dir=target_dir,
        imported_ir_path=imported_ir_path,
        import_report_path=import_report_path,
        ir_lint_path=ir_lint_path,
        workbook_pairwise_report_path=workbook_pairwise_report_path,
        backend_compare_path=backend_compare_path,
        z3_checks_path=z3_checks_path,
        summary_path=summary_path,
        reference_equivalence_report_path=reference_equivalence_report_path,
        reference_equivalence_summary_path=reference_equivalence_summary_path,
    )


def _build_pairwise_report(
    *,
    report_type: str,
    guideline_id: str,
    label: str,
    results: list[Any],
    source_artifacts: dict[str, Any],
) -> dict[str, Any]:
    changed_cases = [result for result in results if not result.ok]
    return {
        "report_type": report_type,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "guideline_id": guideline_id,
        "comparison_label": label,
        "scope": "explicit_case_suite_only",
        "compiler": compiler_metadata(),
        "case_count": len(results),
        "equivalent_on_case_suite": not changed_cases,
        "changed_case_count": len(changed_cases),
        "source_artifacts": source_artifacts,
        "results": [
            {
                "name": result.name,
                "ok": result.ok,
                "inputs": result.inputs,
                "missing": result.missing,
                "mismatches": result.mismatches,
                "mismatch_entries": [
                    {
                        "field": item.field,
                        "category": item.category,
                        "expected_engine": item.expected_engine,
                        "actual_engine": item.actual_engine,
                        "expected_value": item.expected_value,
                        "actual_value": item.actual_value,
                    }
                    for item in result.mismatch_entries
                ],
            }
            for result in results
        ],
    }


def _normalize_workbook_pairwise_results(results: list[Any], workbook: Any) -> list[Any]:
    has_rule_rows = any(getattr(row, "name", "").startswith("rh_") for row in getattr(workbook, "survey", []))
    if has_rule_rows:
        return results
    for result in results:
        paired = list(zip(result.mismatches, result.mismatch_entries, strict=False))
        filtered_pairs = [(message, entry) for message, entry in paired if entry.category != "rule_hit"]
        filtered_entries = [entry for _, entry in filtered_pairs]
        result.mismatch_entries = filtered_entries
        result.mismatches = [message for message, _ in filtered_pairs]
        result.ok = not filtered_entries
    return results


def _clean(value: object) -> object:
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if is_dataclass(value):
        return _clean(asdict(value))
    if hasattr(value, "to_dict"):
        return _clean(value.to_dict())
    if hasattr(value, "value"):
        return _clean(getattr(value, "value"))
    return value
