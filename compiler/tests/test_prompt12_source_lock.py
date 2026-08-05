from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify_prompt12_source_lock.py"
SPEC = importlib.util.spec_from_file_location("verify_prompt12_source_lock", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Prompt12Through14SourceLockTests(unittest.TestCase):
    def test_repository_source_lock_matches_current_reviewed_handoff(self) -> None:
        lock = Path(__file__).resolve().parents[1] / "integration" / "prompt12-source-lock.json"
        source_root = MODULE.configured_source_root(lock)
        if not (source_root / "package.json").is_file():
            self.skipTest("reviewed Prompt 12A-14 handoff is an external integration input")
        self.assertEqual(MODULE.verify(lock), [])

    def _fixture(self, root: Path) -> tuple[Path, Path]:
        source = root / "source"
        source.mkdir()
        (source / "package.json").write_text(
            json.dumps({"name": "reviewed", "version": "1.0.0"}), encoding="utf-8"
        )
        artifact = source / "artifact.txt"
        artifact.write_text("reviewed\n", encoding="utf-8")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        lock = root / "lock.json"
        lock.write_text(
            json.dumps(
                {
                    "source": {"package_name": "reviewed", "package_version": "1.0.0"},
                    "files": [{"path": "artifact.txt", "sha256": f"sha256:{digest}"}],
                }
            ),
            encoding="utf-8",
        )
        return source, lock

    def test_accepts_exact_locked_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            source, lock = self._fixture(Path(raw_root))
            self.assertEqual(MODULE.verify(lock, source), [])

    def test_rejects_changed_and_escaping_source_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            source, lock = self._fixture(root)
            (source / "artifact.txt").write_text("changed\n", encoding="utf-8")
            payload = json.loads(lock.read_text(encoding="utf-8"))
            payload["files"].append({"path": "../outside.txt", "sha256": "sha256:unused"})
            lock.write_text(json.dumps(payload), encoding="utf-8")

            findings = MODULE.verify(lock, source)

            self.assertTrue(any("hash mismatch" in finding for finding in findings))
            self.assertTrue(any("escapes the source root" in finding for finding in findings))


if __name__ == "__main__":
    unittest.main()
