"""Generate Python-owned special-function files and run them in the pinned official CHT harness."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


COMPILER_ROOT = Path(__file__).resolve().parents[1]
SRC = COMPILER_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.cht_special_functions import (
    lower_reviewed_special_functions,
    reviewed_cht_versions,
    write_cht_special_function_bundle,
)


def _source_root() -> Path:
    lock_path = COMPILER_ROOT / "integration" / "prompt12-source-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    repository_root = COMPILER_ROOT.parent
    return (repository_root / lock["source"]["workspace_relative_path"]).resolve()


def main() -> int:
    source_root = _source_root()
    harness_root = source_root / "integration" / "official-cht-harness"
    runner = harness_root / "run-harness.mjs"
    if not runner.is_file() or not (harness_root / "node_modules").is_dir():
        print("ERROR: the locked source harness and installed pinned packages are required", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="chw-python-special-functions-") as temporary:
        workspace = Path(temporary) / "workspace"
        generated_hashes: dict[str, dict[str, str]] = {}
        for version in reviewed_cht_versions():
            source_bundle = (
                harness_root
                / "workspace"
                / version
                / "sick_child_assessment_with_followup"
            )
            target_bundle = workspace / version / "sick_child_assessment_with_followup"
            shutil.copytree(source_bundle, target_bundle)
            bundle = lower_reviewed_special_functions(version)
            for artifact in bundle.files:
                target = target_bundle / artifact.path
                target.unlink()
            write_cht_special_function_bundle(bundle, target_bundle)
            generated_hashes[version] = {
                artifact.path: artifact.sha256
                for artifact in bundle.files
            }

        environment = {
            **os.environ,
            "CHW_OFFICIAL_HARNESS_WORKSPACE": str(workspace),
        }
        result = subprocess.run(
            [shutil.which("node") or "node", str(runner)],
            cwd=harness_root,
            env=environment,
            check=False,
        )
        if result.returncode:
            return result.returncode
        print(
            json.dumps(
                {
                    "status": "pass_with_external_limits",
                    "generator": "authoritative_python_compiler",
                    "profiles": list(reviewed_cht_versions()),
                    "browser_harness_core": "4.11",
                    "generated_hashes": generated_hashes,
                    "external_limits": [
                        "exact CHT 4.22.0 and 5.2.0 target runtime not run",
                        "live CouchDB upload not run",
                        "offline device execution not run",
                        "native WFA chart equivalence not established",
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
