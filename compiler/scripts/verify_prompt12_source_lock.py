"""Verify the reviewed Prompt 12A-14 handoff against its integration source lock."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def configured_source_root(lock_path: Path) -> Path:
    lock = _load_json(lock_path)
    source = lock.get("source")
    if not isinstance(source, dict):
        raise ValueError("source lock has no source object")
    relative = source.get("workspace_relative_path")
    if not isinstance(relative, str) or not relative:
        raise ValueError("source.workspace_relative_path must be a non-empty string")
    repository_root = lock_path.parents[2]
    return (repository_root / relative).resolve()


def verify(lock_path: Path, source_root: Path | None = None) -> list[str]:
    lock = _load_json(lock_path)
    source = lock.get("source")
    if not isinstance(source, dict):
        return ["source lock has no source object"]

    if source_root is None:
        try:
            source_root = configured_source_root(lock_path)
        except ValueError as error:
            return [str(error)]
    else:
        source_root = source_root.resolve()

    findings: list[str] = []
    package_path = source_root / "package.json"
    if not package_path.is_file():
        findings.append(f"missing source package metadata: {package_path}")
    else:
        package = _load_json(package_path)
        for lock_key, package_key in (("package_name", "name"), ("package_version", "version")):
            if package.get(package_key) != source.get(lock_key):
                findings.append(
                    f"package {package_key} mismatch: expected {source.get(lock_key)!r}, got {package.get(package_key)!r}"
                )

    files = lock.get("files")
    if not isinstance(files, list) or not files:
        findings.append("source lock must declare at least one file")
        return findings

    seen: set[str] = set()
    for index, entry in enumerate(files):
        if not isinstance(entry, dict):
            findings.append(f"files[{index}] must be an object")
            continue
        relative_path = entry.get("path")
        expected = entry.get("sha256")
        if not isinstance(relative_path, str) or not relative_path:
            findings.append(f"files[{index}].path must be a non-empty string")
            continue
        if relative_path in seen:
            findings.append(f"duplicate locked path: {relative_path}")
            continue
        seen.add(relative_path)
        candidate = (source_root / relative_path).resolve()
        try:
            candidate.relative_to(source_root)
        except ValueError:
            findings.append(f"locked path escapes the source root: {relative_path}")
            continue
        if not candidate.is_file():
            findings.append(f"missing locked file: {relative_path}")
            continue
        actual = _sha256(candidate)
        if actual != expected:
            findings.append(f"hash mismatch for {relative_path}: expected {expected}, got {actual}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--lock",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "integration" / "prompt12-source-lock.json",
    )
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()

    findings = verify(args.lock.resolve(), args.source_root)
    if findings:
        for finding in findings:
            print(f"ERROR: {finding}", file=sys.stderr)
        return 1
    print("Prompt 12A-14 integration source lock verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
