"""Build the WS2 hand-written tracer from repository-root-relative inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


COMPILER_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = COMPILER_ROOT.parent
SRC = COMPILER_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.tracer import build_tracer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(COMPILER_ROOT / "generated" / "tracer"))
    parser.add_argument("--manifest", default=str(COMPILER_ROOT / "reports" / "tracer-evidence-manifest.json"))
    args = parser.parse_args(argv)
    result = build_tracer(args.output, evidence_manifest=args.manifest)
    evidence = json.loads(result.evidence_manifest.read_text(encoding="utf-8"))
    print(f"tracer_output={result.output_dir}")
    print(f"evidence_manifest={result.evidence_manifest}")
    print(
        f"evidence_level={evidence['evidence_level']} "
        f"deployment_ready={str(evidence['deployment_ready']).lower()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
