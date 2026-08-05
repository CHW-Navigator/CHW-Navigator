"""Run Prompt B evaluation with an optional ``module:function`` adapter."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT.parent))

from backend.operational.prompt_b_evaluation import (  # noqa: E402
    load_evaluation_cases,
    run_prompt_b_evaluation,
)


def _load_adapter(spec: str):
    module_name, separator, attribute = spec.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("adapter must use module:function syntax")
    adapter = getattr(importlib.import_module(module_name), attribute)
    if not callable(adapter):
        raise TypeError("adapter target must be callable")
    return adapter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", help="opt-in live model adapter as module:function")
    parser.add_argument(
        "--cases",
        type=Path,
        default=BACKEND_ROOT / "tests" / "prompt_b_fixtures" / "cases.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=BACKEND_ROOT / "reports" / "prompt-b-live-evaluation.json",
    )
    args = parser.parse_args(argv)
    cases = load_evaluation_cases(args.cases)
    adapter = _load_adapter(args.adapter) if args.adapter else None
    report: dict[str, Any] = run_prompt_b_evaluation(cases, adapter)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.output)}))
    return 0 if report["status"] in {"pass", "not_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
