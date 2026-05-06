from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import tomllib


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_project_version(root: Path | None = None) -> str:
    active_root = root or project_root()
    pyproject_path = active_root / "pyproject.toml"
    if not pyproject_path.exists():
        return "unknown"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    version = project.get("version")
    return str(version) if version else "unknown"


def get_git_commit(root: Path | None = None) -> str | None:
    active_root = root or project_root()
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=active_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip() or None


def compiler_metadata() -> dict[str, Any]:
    return {
        "package": "chw-navigator",
        "version": load_project_version(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "git_commit": get_git_commit(),
    }


def portable_relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def describe_file(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": portable_relative_path(path, root),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def slugify(value: str, *, fallback: str) -> str:
    slug = "".join(character.lower() if character.isalnum() else "-" for character in value)
    collapsed = "-".join(part for part in slug.split("-") if part)
    return collapsed or fallback


def allocate_timestamped_dir(root: Path, label: str, *, fallback_slug: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = slugify(label, fallback=fallback_slug)
    candidate = root / f"{timestamp}-{slug}"
    counter = 2
    while candidate.exists():
        candidate = root / f"{timestamp}-{slug}-{counter:02d}"
        counter += 1
    return candidate
