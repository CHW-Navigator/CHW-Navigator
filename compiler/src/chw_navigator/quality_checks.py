from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

from .clinical_ir import ClinicalIRDocument
from .compare import ComparisonCase, build_comparison_log, build_z3_checks_log, compare_backends, derive_comparison_cases
from .evidence_utils import compiler_metadata
from .mermaid_backend import MermaidOptions, build_mermaid_artifact
from .staged_lint import (
    StageLintIssue,
    lint_ir_document,
    lint_mermaid_artifact,
    lint_smt_artifact,
    lint_xlsform_artifacts,
)
from .xlsform_backend import build_xlsform, write_xlsform_csvs
from .xlsform_proof import build_xlsform_roundtrip_proof
from .z3_backend import analyze_document, export_smt2

_XLSFORM_ONLINE_URL = "https://getodk.org/xlsform/"


@dataclass(slots=True)
class QualityCheckArtifacts:
    root_dir: Path
    ir_lint_path: Path
    survey_path: Path
    choices_path: Path
    xlsform_lint_path: Path
    xlsform_proof_dir: Path
    mermaid_path: Path
    mermaid_lint_path: Path
    smt2_path: Path
    smt_lint_path: Path
    backend_compare_path: Path
    z3_checks_path: Path
    quality_report_path: Path
    summary_path: Path


def run_quality_checks(
    document: ClinicalIRDocument,
    *,
    output_dir: str | Path,
    source_ir_path: str | Path | None = None,
    patient_cases: list[ComparisonCase] | None = None,
) -> QualityCheckArtifacts:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    cases = patient_cases or derive_comparison_cases(document)

    ir_lint = lint_ir_document(
        document,
        source_path=str(source_ir_path) if source_ir_path is not None else None,
    )
    ir_lint_path = target_dir / "ir.lint.json"
    ir_lint_path.write_text(json.dumps(_clean(ir_lint.to_dict()), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    xlsform_dir = target_dir / "xlsform"
    built = build_xlsform(document)
    survey_path_text, choices_path_text, _ = write_xlsform_csvs(built, str(xlsform_dir))
    survey_path = Path(survey_path_text)
    choices_path = Path(choices_path_text)

    xlsform_lint = lint_xlsform_artifacts(survey_path, choices_path)
    xlsform_lint_path = target_dir / "xlsform.lint.json"
    xlsform_lint_path.write_text(json.dumps(_clean(xlsform_lint.to_dict()), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    xlsform_proof_dir = target_dir / "xlsform_roundtrip_proof"
    build_xlsform_roundtrip_proof(
        survey_path=survey_path,
        choices_path=choices_path,
        output_dir=xlsform_proof_dir,
        guideline_id=document.metadata.guideline_id,
        reference_document=document,
        patient_cases=cases,
    )

    mermaid_artifact = build_mermaid_artifact(document, MermaidOptions())
    mermaid_path = target_dir / f"{document.metadata.guideline_id}.mmd"
    mermaid_path.write_text(mermaid_artifact.text, encoding="utf-8")
    mermaid_lint = lint_mermaid_artifact(document, candidate_text=mermaid_artifact.text)
    mermaid_lint_path = target_dir / "mermaid.lint.json"
    mermaid_lint_path.write_text(json.dumps(_clean(mermaid_lint.to_dict()), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    smt2_text = export_smt2(document)
    smt2_path = target_dir / f"{document.metadata.guideline_id}.smt2"
    smt2_path.write_text(smt2_text, encoding="utf-8")
    smt_lint = lint_smt_artifact(document, candidate_text=smt2_text)
    smt_lint_path = target_dir / "smt2.lint.json"
    smt_lint_path.write_text(json.dumps(_clean(smt_lint.to_dict()), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    backend_results = compare_backends(document, patient_cases=cases)
    backend_compare_path = target_dir / "backend_compare.json"
    backend_compare_path.write_text(
        json.dumps(
            build_comparison_log(
                guideline_id=document.metadata.guideline_id,
                results=backend_results,
                compiler_version=compiler_metadata()["version"],
                source_artifacts={
                    "ir_path": str(source_ir_path) if source_ir_path is not None else None,
                    "survey_path": str(survey_path),
                    "choices_path": str(choices_path),
                },
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    z3_report = analyze_document(document)
    z3_checks_path = target_dir / "z3_checks.json"
    z3_checks_path.write_text(
        json.dumps(
            build_z3_checks_log(
                guideline_id=document.metadata.guideline_id,
                report=z3_report,
                compiler_version=compiler_metadata()["version"],
                source_artifacts={
                    "ir_path": str(source_ir_path) if source_ir_path is not None else None,
                    "survey_path": str(survey_path),
                    "choices_path": str(choices_path),
                },
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    blocker_issues = _release_blockers(ir_lint.issues, xlsform_lint.issues, mermaid_lint.issues, smt_lint.issues)
    report = {
        "report_type": "compiled_quality_check",
        "guideline_id": document.metadata.guideline_id,
        "compiler": compiler_metadata(),
        "case_count": len(cases),
        "release_ready": not blocker_issues and all(item.ok for item in (ir_lint, xlsform_lint, mermaid_lint, smt_lint)),
        "release_blockers": [asdict(issue) for issue in blocker_issues],
        "stage_reports": {
            "compiled_ir": ir_lint.to_dict(),
            "xlsform": xlsform_lint.to_dict(),
            "mermaid": mermaid_lint.to_dict(),
            "smt2": smt_lint.to_dict(),
        },
        "backend_compare": {
            "mismatching_case_count": sum(1 for item in backend_results if not item.ok),
            "results_path": str(backend_compare_path),
        },
        "z3_checks_path": str(z3_checks_path),
        "xlsform_roundtrip_proof_dir": str(xlsform_proof_dir),
        "external_validator": {
            "name": "XLSForm Online",
            "url": _XLSFORM_ONLINE_URL,
            "note": "Optional manual upload/preview check after local proof and lint.",
        },
    }
    quality_report_path = target_dir / "quality_report.json"
    quality_report_path.write_text(json.dumps(_clean(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary_path = target_dir / "quality_summary.md"
    summary_lines = [
        "# Compiled Quality Check",
        "",
        f"- Guideline id: `{document.metadata.guideline_id}`",
        f"- Case count: `{len(cases)}`",
        f"- Release ready: `{str(report['release_ready']).lower()}`",
        f"- Release blockers: `{len(blocker_issues)}`",
        f"- Backend mismatching cases: `{report['backend_compare']['mismatching_case_count']}`",
        "",
        "Generated artifacts:",
        f"- XLSForm survey: `{survey_path}`",
        f"- XLSForm choices: `{choices_path}`",
        f"- Mermaid: `{mermaid_path}`",
        f"- SMT-LIB: `{smt2_path}`",
        f"- XLSForm round-trip proof: `{xlsform_proof_dir}`",
        "",
        "Quality checks:",
        f"- IR lint errors: `{_count_level(ir_lint.issues, 'ERROR')}`",
        f"- XLSForm lint errors: `{_count_level(xlsform_lint.issues, 'ERROR')}`",
        f"- Mermaid lint errors: `{_count_level(mermaid_lint.issues, 'ERROR')}`",
        f"- SMT lint errors: `{_count_level(smt_lint.issues, 'ERROR')}`",
        "",
        "Optional external validator:",
        f"- XLSForm Online: `{_XLSFORM_ONLINE_URL}`",
        "",
    ]
    if blocker_issues:
        summary_lines.extend(["Release blockers:", ""])
        for issue in blocker_issues:
            summary_lines.append(f"- `{issue.path}`: {issue.message}")
        summary_lines.append("")
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")

    return QualityCheckArtifacts(
        root_dir=target_dir,
        ir_lint_path=ir_lint_path,
        survey_path=survey_path,
        choices_path=choices_path,
        xlsform_lint_path=xlsform_lint_path,
        xlsform_proof_dir=xlsform_proof_dir,
        mermaid_path=mermaid_path,
        mermaid_lint_path=mermaid_lint_path,
        smt2_path=smt2_path,
        smt_lint_path=smt_lint_path,
        backend_compare_path=backend_compare_path,
        z3_checks_path=z3_checks_path,
        quality_report_path=quality_report_path,
        summary_path=summary_path,
    )


def _release_blockers(*issue_lists: list[StageLintIssue]) -> list[StageLintIssue]:
    blockers: list[StageLintIssue] = []
    seen: set[tuple[str, str, str]] = set()
    for issues in issue_lists:
        for issue in issues:
            is_blocker = issue.level == "ERROR" or "no documented collection path" in issue.message
            if not is_blocker:
                continue
            key = (issue.level, issue.path, issue.message)
            if key in seen:
                continue
            seen.add(key)
            blockers.append(issue)
    return blockers


def _count_level(issues: list[StageLintIssue], level: str) -> int:
    return sum(1 for issue in issues if issue.level == level)


def _clean(value: Any) -> Any:
    if is_dataclass(value):
        return _clean(asdict(value))
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value
