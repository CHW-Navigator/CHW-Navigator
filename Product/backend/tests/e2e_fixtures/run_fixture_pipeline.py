"""Run the synthetic corpus through its safe, auditable test pipeline.

The default deterministic mode processes every fixture: source-admission gate,
function-registry gate, independent raw-input oracle, Prompt 9 / Prompt 10
planning where eligible, and local-only task/message recording.  It does not
call a model or make an external effect.

``--live`` is intentionally separate.  It calls the configured Gen 8 clinical
extraction pipeline only for eligible complete manuals.  The operational
comparison and local sinks still remain local; no provider or message adapter
is present in this test lab.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

from backend.tests.e2e_fixtures.local_extensions import LocalRunRecorder
from backend.tests.e2e_fixtures.reference_oracle import evaluate_fixture_case


ROOT = Path(__file__).resolve().parent
PACKAGES = ROOT / "packages"
COMMON = ROOT / "common"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _packages() -> list[tuple[Path, dict[str, Any]]]:
    return [(path, _load(path)) for path in sorted(PACKAGES.glob("*.json"))]


def _registry_aliases(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    aliases: dict[str, dict[str, Any]] = {}
    for entry in registry["functions"]:
        aliases[entry["id"].split("@", 1)[0]] = entry
        for alias in entry.get("aliases", []):
            aliases[alias] = entry
    return aliases


def _registry_findings(package: dict[str, Any], registry: dict[str, Any]) -> list[dict[str, str]]:
    aliases = _registry_aliases(registry)
    findings: list[dict[str, str]] = []
    for function in package["function_profile"].get("functions", []):
        entry = aliases.get(function)
        if entry is None:
            findings.append({"function": function, "state": "unregistered"})
        else:
            findings.append({"function": function, "entry_id": entry["id"], "state": entry["state"]})
    return findings


def _admission(package: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    status = package["fixture_status"]
    if status == "source_blocked":
        return {"status": "blocked", "reason": package["source_oracle"]["required_finding"]}
    if status == "setup_blocked":
        return {"status": "blocked", "reason": "setup_validation_error"}
    findings = _registry_findings(package, registry)
    unavailable = [item for item in findings if item["state"] in {"unavailable", "unregistered"}]
    if unavailable:
        return {"status": "blocked", "reason": "extension_not_available", "functions": unavailable}
    return {"status": "eligible", "registry": findings}


def run_deterministic(output_dir: Path) -> dict[str, Any]:
    """Run every synthetic fixture without any model or external side effect."""
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite an existing test run: {output_dir}")
    output_dir.mkdir(parents=True)
    recorder = LocalRunRecorder(output_dir)
    registry = _load(COMMON / "extension-registry.json")
    rows: list[dict[str, Any]] = []
    for _, package in _packages():
        fixture_id = package["fixture_id"]
        admission = _admission(package, registry)
        for case in package["patient_cases"]:
            actual = evaluate_fixture_case(package, case["inputs"])
            expected = case["expected"]
            matches = all(
                actual.get(field) == value
                for field, value in expected.items()
                if field != "forbidden_outputs"
            )
            row = {
                "fixture_id": fixture_id,
                "case_id": case["id"],
                "admission": admission,
                "actual": actual,
                "expected": expected,
                "matches_oracle": matches,
            }
            rows.append(row)
            if actual.get("status") == "planned":
                recorder.create_task(
                    fixture_id=fixture_id,
                    case_id=case["id"],
                    task_type="local.review-follow-up@1.0.0",
                    status="planned_not_queued",
                )
                recorder.write_message_file(
                    fixture_id=fixture_id,
                    case_id=case["id"],
                    message_type="local.file-notice@1.0.0",
                    text="Synthetic follow-up plan recorded locally; no message was sent.",
                )
            if actual.get("status") == "blocked":
                recorder.write_screen(
                    fixture_id=fixture_id,
                    case_id=case["id"],
                    text=f"Blocked safely: {actual.get('reason', 'admission gate')}",
                )
    summary = {
        "mode": "deterministic",
        "fixture_count": len({row["fixture_id"] for row in rows}),
        "case_count": len(rows),
        "oracle_matches": sum(1 for row in rows if row["matches_oracle"]),
        "blocked_cases": sum(1 for row in rows if row["actual"].get("status") == "blocked"),
        "local_only": True,
        "rows": rows,
    }
    (output_dir / "fixture_pipeline_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if summary["oracle_matches"] != summary["case_count"]:
        raise AssertionError("one or more fixture cases diverged from the independent oracle")
    return summary


async def run_live(fixture_id: str, output_dir: Path) -> dict[str, Any]:
    """Run Gen 8 clinical extraction on one complete, eligible synthetic guide."""
    package_path, package = next((item for item in _packages() if item[1]["fixture_id"] == fixture_id), (None, None))
    if package is None or package_path is None:
        raise ValueError(f"unknown fixture ID: {fixture_id}")
    if package["fixture_status"] != "complete":
        raise ValueError("live extraction accepts only complete fixtures; expected-blocked packages stop at admission")
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for --live")
    missing = [name for name in ("anthropic", "rlm", "z3") if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError(
            "live extraction environment is incomplete; missing "
            + ", ".join(missing)
            + ". Install Product/backend/requirements.txt in the selected Python environment."
        )
    from backend.gen8.pipeline import run

    guide_path = package_path.parent / package_path.stem / "guide.json"
    live_output = output_dir.resolve() / "live" / fixture_id
    if live_output.exists():
        raise FileExistsError(f"refusing to overwrite an existing live test run: {live_output}")
    result = await run(
        _load(guide_path),
        key,
        output_dir=live_output,
        manual_name_hint=package["title"],
        labeler="opus",
        run_verifier=False,
    )
    report = {
        "mode": "live_gen8_clinical_extraction",
        "fixture_id": fixture_id,
        "status": result["status"],
        "output_dir": str(live_output),
        "clinical_logic_keys": sorted(result["clinical_logic"]),
        "external_effect_package": result["external_effect_package"],
        "effect_boundary": "No topology or external-effect sidecar was passed to the live clinical run; no delivery action exists.",
    }
    (live_output / "fixture_live_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "runs" / "deterministic")
    parser.add_argument("--live", metavar="FIXTURE_ID", help="Run Gen 8 extraction for one complete synthetic fixture.")
    args = parser.parse_args()
    if args.live:
        report = asyncio.run(run_live(args.live, args.output_dir))
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        summary = run_deterministic(args.output_dir)
        print(json.dumps({key: summary[key] for key in summary if key != "rows"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
