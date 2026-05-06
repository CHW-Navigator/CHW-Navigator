from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .clinical_ir import ClinicalIRDocument
from .compare import ComparisonCase, compare_document_pair
from .evidence_utils import compiler_metadata


@dataclass(slots=True)
class EquivalenceArtifacts:
    report_path: Path
    summary_path: Path


def build_case_suite_equivalence_report(
    *,
    baseline_document: ClinicalIRDocument,
    candidate_document: ClinicalIRDocument,
    patient_cases: list[ComparisonCase],
    output_dir: str | Path,
    baseline_label: str = "baseline",
    candidate_label: str = "candidate",
) -> EquivalenceArtifacts:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    results = compare_document_pair(
        baseline_document,
        candidate_document,
        patient_cases,
        label=candidate_label,
    )
    changed_cases = [result for result in results if not result.ok]
    output_changed_cases = [result for result in changed_cases if _case_has_category(result, "output")]
    predicate_changed_cases = [result for result in changed_cases if _case_has_category(result, "predicate")]
    rule_hit_changed_cases = [result for result in changed_cases if _case_has_category(result, "rule_hit")]
    report = {
        "report_type": "case_suite_equivalence",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "scope": "explicit_case_suite_only",
        "compiler": compiler_metadata(),
        "baseline_label": baseline_label,
        "candidate_label": candidate_label,
        "case_count": len(results),
        "equivalent_on_case_suite": not changed_cases,
        "equivalent_outputs_on_case_suite": not output_changed_cases,
        "changed_case_count": len(changed_cases),
        "output_changed_case_count": len(output_changed_cases),
        "predicate_changed_case_count": len(predicate_changed_cases),
        "rule_hit_changed_case_count": len(rule_hit_changed_cases),
        "results": [_clean_case_result(item) for item in results],
    }
    report_path = target_dir / "equivalence_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary_lines = [
        "# Clinical Equivalence Report",
        "",
        f"- Scope: `explicit_case_suite_only`",
        f"- Baseline: `{baseline_label}`",
        f"- Candidate: `{candidate_label}`",
        f"- Case count: `{len(results)}`",
        f"- Equivalent on supplied case suite: `{str(not changed_cases).lower()}`",
        f"- Output-equivalent on supplied case suite: `{str(not output_changed_cases).lower()}`",
        f"- Changed cases (any semantic mismatch): `{len(changed_cases)}`",
        f"- Changed cases with output differences: `{len(output_changed_cases)}`",
        f"- Changed cases with predicate differences: `{len(predicate_changed_cases)}`",
        f"- Changed cases with rule-hit differences: `{len(rule_hit_changed_cases)}`",
        "",
        "This report does not claim whole-proof-space equivalence. It only reports agreement or disagreement on the supplied explicit patient suite.",
    ]
    if changed_cases:
        summary_lines.extend(["", "## Changed Cases", ""])
        for result in changed_cases:
            summary_lines.append(f"- `{result.name}`: {len(result.mismatch_entries)} mismatch(es)")
    summary_path = target_dir / "equivalence_summary.md"
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return EquivalenceArtifacts(report_path=report_path, summary_path=summary_path)


def _clean_case_result(result: Any) -> dict[str, Any]:
    return {
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


def _case_has_category(result: Any, category: str) -> bool:
    return any(item.category == category for item in result.mismatch_entries)
